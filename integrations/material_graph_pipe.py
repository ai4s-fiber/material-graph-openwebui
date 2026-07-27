"""Version-compatible Material Graph Pipe for Open WebUI v0.10.2."""

from __future__ import annotations

import json
import time
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable
from threading import RLock
from typing import Any

import httpx
from open_webui.utils.material_graph_auth import build_material_graph_auth_headers
from pydantic import BaseModel, Field

GRAPH = {
    'workflowdefinition',
    'workflow_definition',
    'workflow',
    'graph',
    'graph_snapshot',
    'graph_delta',
}
NODE = {'nodestate', 'node_state', 'node_status', 'node'}
TOKEN = {'token', 'text_delta', 'delta', 'assistant_token', 'assistant_delta', 'assistant_message'}
LOG = {'log', 'workflow_log', 'node_log'}
FORM = {'assistant_form', 'assistantform', 'form'}
TERMINAL = {
    'terminal',
    'terminal_outcome',
    'outcome',
    'run_completed',
    'run_terminal',
    'done',
}
FAILURE = {
    'failed',
    'failure',
    'error',
    'blocked',
    'budget_stopped',
    'budget_exceeded',
    'rejected',
    'cancelled',
    'canceled',
}


class Pipe:
    class Valves(BaseModel):
        material_graph_api_url: str = Field(default='http://material-graph-api:8000')
        material_graph_public_proxy_url: str = Field(default='/api/v1/material-graph')
        timeout_seconds: float = Field(default=180.0, ge=5.0, le=1800.0)
        scenario: str = Field(default='generic_material')
        run_state_max_entries: int = Field(default=512, ge=1, le=10000)
        run_state_ttl_seconds: float = Field(default=1800.0, ge=1.0, le=86400.0)
        run_state_terminal_ttl_seconds: float = Field(default=60.0, ge=0.0, le=3600.0)

    def __init__(self):
        self.name = 'Material Graph Studio'
        self.valves = self.Valves()
        self._runs: dict[str, dict[str, Any]] = {}
        self._run_access: OrderedDict[str, tuple[float, float | None]] = OrderedDict()
        self._runs_lock = RLock()
        self._clock: Callable[[], float] = time.monotonic

    def _evict_run_locked(self, run_id: str) -> None:
        self._runs.pop(run_id, None)
        self._run_access.pop(run_id, None)

    def _prune_runs_locked(self, now: float) -> None:
        active_ttl = float(self.valves.run_state_ttl_seconds)
        terminal_ttl = float(self.valves.run_state_terminal_ttl_seconds)
        expired = []
        for run_id, (last_seen, terminal_at) in self._run_access.items():
            origin = terminal_at if terminal_at is not None else last_seen
            ttl = terminal_ttl if terminal_at is not None else active_ttl
            if ttl == 0 or now - origin >= ttl:
                expired.append(run_id)
        for run_id in expired:
            self._evict_run_locked(run_id)

    def _trim_runs_locked(self, *, protected_run_id: str | None = None) -> None:
        maximum = max(1, int(self.valves.run_state_max_entries))
        while len(self._runs) > maximum:
            terminal_run = next(
                (
                    run_id
                    for run_id, (_, terminal_at) in self._run_access.items()
                    if terminal_at is not None and run_id != protected_run_id
                ),
                None,
            )
            lru_run = next(
                (run_id for run_id in self._run_access if run_id != protected_run_id),
                protected_run_id,
            )
            victim = terminal_run or lru_run
            if victim is None:
                break
            self._evict_run_locked(victim)

    def _run_state_locked(self, run_id: str, now: float) -> dict[str, Any]:
        self._prune_runs_locked(now)
        state = self._runs.get(run_id)
        previous = self._run_access.pop(run_id, None)
        if state is None:
            state = {'nodes': [], 'edges': [], 'logs': [], 'graph_version': None}
            self._runs[run_id] = state
        terminal_at = previous[1] if previous is not None else None
        self._run_access[run_id] = (now, terminal_at)
        self._trim_runs_locked(protected_run_id=run_id)
        return state

    def _finish_run_locked(
        self,
        run_id: str,
        state: dict[str, Any],
        now: float,
    ) -> dict[str, Any]:
        result = {'action': 'material_graph', 'run_id': run_id, **state}
        previous = self._run_access.pop(run_id, None)
        terminal_at = previous[1] if previous is not None else None
        if state.get('done'):
            terminal_at = terminal_at if terminal_at is not None else now
        else:
            terminal_at = None
        self._run_access[run_id] = (now, terminal_at)
        self._prune_runs_locked(now)
        self._trim_runs_locked()
        return result

    async def pipe(
        self,
        body: dict[str, Any],
        __event_emitter__=None,
        __user__=None,
        **_: Any,
    ) -> AsyncIterator[str]:
        messages = body.get('messages') or []
        message = next(
            (str(item.get('content', '')) for item in reversed(messages) if item.get('role') == 'user'),
            '',
        )
        payload = {
            'message': message,
            'scenario': body.get('scenario') or self.valves.scenario,
            'auto_approve': False,
        }
        if isinstance(body.get('material_graph_task'), dict):
            payload['task'] = body['material_graph_task']
        user = __user__ if isinstance(__user__, dict) else {}
        user_id = str(user.get('id') or '').strip()
        if not user_id:
            raise RuntimeError('Material Graph requires an authenticated Open WebUI user')
        raw_roles = user.get('roles') if isinstance(user.get('roles'), list) else [user.get('role') or 'user']
        path = '/chat/stream'

        def auth_headers(method: str, target: str) -> dict[str, str]:
            return build_material_graph_auth_headers(
                user_id=user_id,
                roles=raw_roles,
                method=method,
                path=target,
            )

        headers = {
            'Content-Type': 'application/json',
            'Accept': 'text/event-stream',
            **auth_headers('POST', path),
        }
        content = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        base = self.valves.material_graph_api_url.rstrip('/')
        public_base = self.valves.material_graph_public_proxy_url.rstrip('/')
        timeout = httpx.Timeout(self.valves.timeout_seconds, connect=15.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                'POST',
                f'{base}{path}',
                content=content,
                headers=headers,
            ) as response:
                response.raise_for_status()
                lines: list[str] = []
                async for line in response.aiter_lines():
                    if line.startswith('data:'):
                        lines.append(line[5:].lstrip())
                    elif not line and lines:
                        event = json.loads('\n'.join(lines))
                        async for token in self._forward_event(
                            event,
                            public_base,
                            __event_emitter__,
                            client=client,
                            resync_base_url=base,
                            auth_headers=auth_headers,
                        ):
                            yield token
                        lines = []
                if lines:
                    event = json.loads('\n'.join(lines))
                    async for token in self._forward_event(
                        event,
                        public_base,
                        __event_emitter__,
                        client=client,
                        resync_base_url=base,
                        auth_headers=auth_headers,
                    ):
                        yield token

    @staticmethod
    def _payload(event: dict[str, Any]) -> tuple[str, str | None, dict[str, Any]]:
        version = event.get('contract_version') or event.get('version') or event.get('schema_version')
        envelope = event.get('event')
        if isinstance(envelope, dict) and envelope.get('type') == 'status' and isinstance(envelope.get('data'), dict):
            return 'status', str(version) if version is not None else None, envelope['data']
        source = envelope if isinstance(envelope, dict) else event
        version = source.get('contract_version') or source.get('version') or source.get('schema_version') or version
        name = source.get('type') or source.get('event_type') or event.get('type') or ''
        data = source.get('data') or source.get('payload')
        return (
            str(name).lower(),
            str(version) if version is not None else None,
            data if isinstance(data, dict) else source,
        )

    @staticmethod
    def _integer(value: Any) -> int | None:
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    @staticmethod
    def _replace_nodes(state: dict[str, Any], updates: list[Any]) -> None:
        by_id = {
            str(node.get('id')): index
            for index, node in enumerate(state['nodes'])
            if isinstance(node, dict) and node.get('id') is not None
        }
        nodes = list(state['nodes'])
        for raw_node in updates:
            if not isinstance(raw_node, dict) or raw_node.get('id') is None:
                continue
            node = dict(raw_node)
            node_id = str(node['id'])
            if node_id in by_id:
                nodes[by_id[node_id]] = node
            else:
                by_id[node_id] = len(nodes)
                nodes.append(node)
        state['nodes'] = nodes

    def _apply_v2_graph(  # noqa: C901 - one compatibility reducer owns the protocol variants
        self, kind: str, data: dict[str, Any], state: dict[str, Any]
    ) -> bool:
        incoming_version = self._integer(data.get('graph_version'))
        if kind == 'graph_snapshot':
            workflow = data.get('workflow') or data.get('workflow_definition')
            if isinstance(workflow, dict):
                state['workflow'] = workflow
            if isinstance(data.get('nodes'), list):
                state['nodes'] = list(data['nodes'])
            elif isinstance(workflow, dict) and isinstance(workflow.get('nodes'), list):
                state['nodes'] = list(workflow['nodes'])
            if isinstance(data.get('edges'), list):
                state['edges'] = list(data['edges'])
            elif isinstance(workflow, dict) and isinstance(workflow.get('edges'), list):
                state['edges'] = list(workflow['edges'])
            for key in (
                'current_node',
                'route_signal',
                'elapsed_ms',
                'evidence_count',
                'done',
                'success',
                'outcome',
                'checkpoint_id',
            ):
                if key in data:
                    state[key] = data[key]
            if isinstance(data.get('logs'), list):
                state['logs'] = list(data['logs'])
            if incoming_version is not None:
                state['graph_version'] = incoming_version
            state['resync_required'] = False
            state.pop('resync_url', None)
            return True

        if kind != 'graph_delta':
            return False
        base_version = self._integer(data.get('base_version'))
        current_version = self._integer(state.get('graph_version'))
        if (
            incoming_version is None
            or base_version is None
            or current_version is None
            or base_version != current_version
            or incoming_version != base_version + 1
        ):
            state['resync_required'] = True
            state['resync_url'] = data.get('resync_url')
            return True

        patch = data.get('patch')
        if not isinstance(patch, dict):
            state['resync_required'] = True
            state['resync_url'] = data.get('resync_url')
            return True
        set_values = patch.get('set')
        if isinstance(set_values, dict):
            state.update(set_values)
        unset = patch.get('unset')
        if isinstance(unset, list):
            for key in unset:
                state.pop(str(key), None)
        node_updates = patch.get('node_updates')
        if isinstance(node_updates, list):
            self._replace_nodes(state, node_updates)
        if 'logs' in patch:
            state['logs'] = list(patch['logs']) if isinstance(patch['logs'], list) else []
        state['graph_version'] = incoming_version
        state['resync_required'] = False
        state.pop('resync_url', None)
        return True

    def _status(  # noqa: C901 - legacy and v2 events intentionally share one adapter boundary
        self, name: str, version: str | None, data: dict[str, Any], base: str
    ) -> dict[str, Any] | None:
        action = data.get('action')
        kind = str(data.get('event_type') or data.get('kind') or name).lower()
        run = data.get('run_id') or data.get('runId')
        if action == 'assistant_form' or kind in FORM:
            form = data.get('form') if isinstance(data.get('form'), dict) else data
            return {
                **form,
                'action': 'assistant_form',
                'run_id': form.get('run_id') or form.get('runId') or run,
                'form_id': form.get('form_id') or form.get('formId') or form.get('id'),
                'endpoint': base,
                'contract_version': version or 'legacy',
            }
        if action == 'material_graph':
            kind = str(data.get('event_type') or kind or 'graph').lower()
        if kind not in GRAPH | NODE | LOG | TERMINAL and action != 'material_graph':
            return None
        if not run:
            return None
        with self._runs_lock:
            return self._graph_status_locked(str(run), kind, version, data)

    def _graph_status_locked(  # noqa: C901 - one locked reducer owns legacy compatibility
        self,
        run_id: str,
        kind: str,
        version: str | None,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        now = self._clock()
        state = self._run_state_locked(run_id, now)
        if self._apply_v2_graph(kind, data, state):
            state['contract_version'] = (
                version or data.get('contract_version') or state.get('contract_version') or 'legacy'
            )
            return self._finish_run_locked(run_id, state, now)

        workflow = data.get('workflow') or data.get('workflow_definition') or data.get('definition')
        if isinstance(workflow, dict):
            state['workflow'] = workflow
            state['nodes'] = workflow.get('nodes') or state['nodes']
            state['edges'] = workflow.get('edges') or state['edges']
        if isinstance(data.get('nodes'), list):
            state['nodes'] = data['nodes']
        if isinstance(data.get('edges'), list):
            state['edges'] = data['edges']

        node = data.get('node') if isinstance(data.get('node'), dict) else {}
        node_id = data.get('node_id') or data.get('nodeId') or node.get('id')
        node_status = data.get('status') or data.get('state') or node.get('status')
        if kind in NODE and node_id:
            found = False
            nodes = []
            for old in state['nodes']:
                if old.get('id') == node_id:
                    nodes.append({**old, **node, 'status': node_status or old.get('status')})
                    found = True
                else:
                    nodes.append(old)
            if not found:
                nodes.append(
                    {
                        **node,
                        'id': node_id,
                        'label': node.get('label') or str(node_id),
                        'status': node_status,
                    }
                )
            state['nodes'] = nodes
            if data.get('authoritative', True):
                state['current_node'] = node_id
        if kind in LOG:
            log = data.get('log')
            if not isinstance(log, dict):
                log = {
                    'node_id': node_id,
                    'message': data.get('message') or str(log or ''),
                    'status': node_status,
                    'timestamp': data.get('timestamp'),
                }
            if log.get('message'):
                state['logs'] = [*state['logs'], log]

        outcome = data.get('outcome') or data.get('terminal_outcome')
        if isinstance(outcome, dict):
            outcome = outcome.get('status') or outcome.get('outcome') or outcome.get('type')
        if kind in TERMINAL and not outcome:
            outcome = node_status or data.get('status')
        if outcome:
            outcome = str(outcome).lower().replace('-', '_')
            state.update(
                outcome=outcome,
                done=True,
                success=outcome not in FAILURE and outcome in {'success', 'succeeded', 'complete', 'completed'},
            )
        for source, target in (
            ('current_node', 'current_node'),
            ('currentNode', 'current_node'),
            ('elapsed_ms', 'elapsed_ms'),
            ('evidence_count', 'evidence_count'),
            ('checkpoint_id', 'checkpoint_id'),
            ('checkpointId', 'checkpoint_id'),
            ('error_code', 'error_code'),
            ('retryable', 'retryable'),
            ('retry_after_seconds', 'retry_after_seconds'),
        ):
            if source in data:
                state[target] = data[source]
        if 'done' in data:
            state['done'] = bool(data['done'])
        if 'success' in data:
            state['success'] = bool(data['success'])
        state['contract_version'] = version or data.get('contract_version') or state.get('contract_version') or 'legacy'
        return self._finish_run_locked(run_id, state, now)

    async def _resync(
        self,
        status: dict[str, Any],
        status_base_url: str,
        resync_base_url: str,
        client: httpx.AsyncClient | None,
        auth_headers: Callable[[str, str], dict[str, str]] | None,
    ) -> dict[str, Any]:
        path = status.get('resync_url')
        if not isinstance(path, str) or not path.startswith('/') or path.startswith('//'):
            return status
        owns_client = client is None
        active_client = client or httpx.AsyncClient(timeout=httpx.Timeout(self.valves.timeout_seconds, connect=15.0))
        params = httpx.QueryParams({'known_version': status.get('graph_version')})
        target = f'{path}?{params}'
        headers = auth_headers('GET', target) if auth_headers is not None else None
        try:
            response = await active_client.get(
                f'{resync_base_url.rstrip("/")}{target}',
                headers=headers,
            )
            if response.status_code != 200:
                return status
            name, version, data = self._payload(response.json())
            refreshed = self._status(name, version, data, status_base_url)
            return refreshed or status
        except httpx.HTTPError:
            return status
        finally:
            if owns_client:
                await active_client.aclose()

    async def _forward_event(
        self,
        event: dict[str, Any],
        base_url: str,
        emitter,
        *,
        client: httpx.AsyncClient | None = None,
        resync_base_url: str | None = None,
        auth_headers: Callable[[str, str], dict[str, str]] | None = None,
    ) -> AsyncIterator[str]:
        name, version, data = self._payload(event)
        status = self._status(name, version, data, base_url)
        if status is not None and status.get('resync_required'):
            status = await self._resync(
                status,
                base_url,
                resync_base_url or base_url,
                client,
                auth_headers,
            )
        if status is not None and emitter is not None:
            await emitter({'type': 'status', 'data': status})
        elif name == 'status' and emitter is not None and isinstance(event.get('event'), dict):
            await emitter(event['event'])

        token = event.get('delta') or event.get('token')
        if not token and name in TOKEN:
            token = data.get('delta') or data.get('token') or data.get('text') or data.get('content')
        if token:
            yield str(token)
        error = event.get('error') or data.get('error')
        if error:
            raise RuntimeError(str(error))
