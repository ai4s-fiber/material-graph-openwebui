"""Version-compatible Material Graph Pipe for Open WebUI v0.10.2."""

from __future__ import annotations

import json
import re
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
TITLE_GENERATION = 'title_generation'
TAGS_GENERATION = 'tags_generation'
FOLLOW_UP_GENERATION = 'follow_up_generation'
KNOWLEDGE_SIGNAL = 'knowledge_signal'
SAFE_BACKGROUND_TASKS = {
    TITLE_GENERATION,
    TAGS_GENERATION,
    FOLLOW_UP_GENERATION,
}
TITLE_MAX_LENGTH = 64
CONVERSATION_ID_MAX_LENGTH = 128
HISTORY_MAX_ENTRIES = 24
HISTORY_MAX_CONTENT_CHARS = 16_000
HISTORY_MAX_CONTENT_BYTES = 262_144
CONVERSATION_STATE_MAX_BYTES = 65_536
CONVERSATION_STATE_MAX_DEPTH = 8
CONVERSATION_STATE_MAX_ITEMS = 512
CONVERSATION_ID_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:-]*$')
CONVERSATION_STATE_CACHE_PREFIX = '\x00conversation_state:'
CONVERSATION_STATE_PRIVATE_KEYS = {
    'files',
    'status',
    'statushistory',
}


class Pipe:
    class Valves(BaseModel):
        material_graph_api_url: str = Field(default='http://material-graph-api:8000')
        material_graph_public_proxy_url: str = Field(default='/api/v1/material-graph')
        timeout_seconds: float = Field(default=180.0, ge=5.0, le=1800.0)
        scenario: str = Field(default='custom')
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

    @staticmethod
    def _background_task_name(
        body: dict[str, Any],
        explicit_task: Any,
        explicit_metadata: Any,
    ) -> str | None:
        metadata = body.get('metadata')
        metadata = metadata if isinstance(metadata, dict) else {}
        explicit_metadata = explicit_metadata if isinstance(explicit_metadata, dict) else {}
        raw_task = explicit_task
        if raw_task is None:
            raw_task = explicit_metadata.get('task')
        if raw_task is None:
            raw_task = metadata.get('task')
        if raw_task is None:
            return None
        task = str(raw_task).strip().lower()
        if not task:
            return None
        return task.rsplit('.', 1)[-1]

    @staticmethod
    def _content_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return ''
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get('type') == 'text':
                parts.append(str(item.get('text') or ''))
        return ' '.join(parts)

    @staticmethod
    def _normalized_conversation_id(raw: Any) -> str | None:
        if not isinstance(raw, str):
            return None
        conversation_id = raw.strip()
        if (
            not conversation_id
            or len(conversation_id) > CONVERSATION_ID_MAX_LENGTH
            or CONVERSATION_ID_PATTERN.fullmatch(conversation_id) is None
        ):
            return None
        return conversation_id

    @classmethod
    def _conversation_id(cls, body: dict[str, Any], metadata: Any) -> str | None:
        explicit = metadata if isinstance(metadata, dict) else {}
        embedded = body.get('metadata')
        embedded = embedded if isinstance(embedded, dict) else {}
        raw = explicit.get('chat_id') or embedded.get('chat_id') or body.get('chat_id')
        return cls._normalized_conversation_id(raw)

    @classmethod
    def _bounded_conversation_state(  # noqa: C901 - one recursive JSON boundary owns all limits
        cls, value: Any
    ) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None

        item_count = 0
        active: set[int] = set()

        def project(item: Any, depth: int) -> Any:  # noqa: C901
            nonlocal item_count
            if depth > CONVERSATION_STATE_MAX_DEPTH:
                raise ValueError('conversation state is too deep')
            item_count += 1
            if item_count > CONVERSATION_STATE_MAX_ITEMS:
                raise ValueError('conversation state has too many items')

            if isinstance(item, dict):
                identity = id(item)
                if identity in active:
                    raise ValueError('conversation state is cyclic')
                active.add(identity)
                try:
                    projected = {}
                    for key, child in item.items():
                        if not isinstance(key, str):
                            raise TypeError('conversation state keys must be strings')
                        private_key = key.casefold().replace('_', '')
                        if private_key in CONVERSATION_STATE_PRIVATE_KEYS:
                            continue
                        projected[key] = project(child, depth + 1)
                    return projected
                finally:
                    active.remove(identity)

            if isinstance(item, list):
                identity = id(item)
                if identity in active:
                    raise ValueError('conversation state is cyclic')
                active.add(identity)
                try:
                    return [project(child, depth + 1) for child in item]
                finally:
                    active.remove(identity)

            if item is None or isinstance(item, str | int | float | bool):
                return item
            raise TypeError('conversation state must be JSON compatible')

        try:
            projected = project(value, 0)
            encoded = json.dumps(
                projected,
                ensure_ascii=False,
                separators=(',', ':'),
                allow_nan=False,
            ).encode('utf-8')
        except (TypeError, ValueError, UnicodeEncodeError):
            return None
        if not projected or len(encoded) > CONVERSATION_STATE_MAX_BYTES:
            return None
        return projected

    @staticmethod
    def _conversation_state_cache_key(conversation_id: str) -> str:
        return f'{CONVERSATION_STATE_CACHE_PREFIX}{conversation_id}'

    def _cached_conversation_state(self, conversation_id: str) -> dict[str, Any] | None:
        cache_key = self._conversation_state_cache_key(conversation_id)
        with self._runs_lock:
            now = self._clock()
            self._prune_runs_locked(now)
            state = self._runs.get(cache_key)
            if not isinstance(state, dict):
                return None
            cached = self._bounded_conversation_state(state.get('conversation_state'))
            if cached is None:
                self._evict_run_locked(cache_key)
                return None
            previous = self._run_access.pop(cache_key, None)
            terminal_at = previous[1] if previous is not None else None
            self._run_access[cache_key] = (now, terminal_at)
            return cached

    def _remember_conversation_state(
        self,
        expected_conversation_id: str | None,
        event_name: str,
        data: dict[str, Any],
    ) -> None:
        if expected_conversation_id is None or event_name not in {'assistant_message', 'done'}:
            return
        conversation_id = self._normalized_conversation_id(data.get('conversation_id'))
        if conversation_id != expected_conversation_id:
            return
        conversation_state = self._bounded_conversation_state(data.get('conversation_state'))
        if conversation_state is None:
            return
        cache_key = self._conversation_state_cache_key(conversation_id)
        with self._runs_lock:
            now = self._clock()
            self._prune_runs_locked(now)
            self._runs[cache_key] = {'conversation_state': conversation_state}
            self._run_access.pop(cache_key, None)
            self._run_access[cache_key] = (now, None)
            self._trim_runs_locked(protected_run_id=cache_key)

    @staticmethod
    def _current_user_index(messages: list[Any]) -> int | None:
        return next(
            (
                index
                for index in range(len(messages) - 1, -1, -1)
                if isinstance(messages[index], dict) and messages[index].get('role') == 'user'
            ),
            None,
        )

    @classmethod
    def _normalized_history_item(cls, item: Any) -> dict[str, str] | None:
        if not isinstance(item, dict):
            return None
        role = item.get('role')
        if role not in {'user', 'assistant'}:
            return None
        content = cls._content_text(item.get('content')).strip()
        if not content:
            return None
        return {
            'role': role,
            'content': content[:HISTORY_MAX_CONTENT_CHARS],
        }

    @classmethod
    def _conversation_history(cls, messages: Any) -> list[dict[str, str]]:
        if not isinstance(messages, list):
            return []

        current_user_index = cls._current_user_index(messages)
        if current_user_index is None:
            return []

        normalized = [
            normalized_item
            for item in messages[:current_user_index]
            if (normalized_item := cls._normalized_history_item(item)) is not None
        ]

        retained: list[dict[str, str]] = []
        remaining_bytes = HISTORY_MAX_CONTENT_BYTES
        for item in reversed(normalized[-HISTORY_MAX_ENTRIES:]):
            encoded = item['content'].encode('utf-8')
            if len(encoded) > remaining_bytes:
                encoded = encoded[:remaining_bytes]
                content = encoded.decode('utf-8', errors='ignore')
                if not content:
                    break
                encoded = content.encode('utf-8')
                item = {**item, 'content': content}
            retained.append(item)
            remaining_bytes -= len(encoded)
            if remaining_bytes <= 0:
                break
        retained.reverse()
        return retained

    @classmethod
    def _deterministic_title(cls, *sources: Any) -> str:
        for source in sources:
            if not isinstance(source, dict):
                continue
            messages = source.get('messages')
            if not isinstance(messages, list):
                continue
            for message in messages:
                if not isinstance(message, dict) or message.get('role') != 'user':
                    continue
                title = ' '.join(cls._content_text(message.get('content')).split())
                if not title:
                    continue
                if len(title) > TITLE_MAX_LENGTH:
                    return f'{title[: TITLE_MAX_LENGTH - 3]}...'
                return title
        return '新对话'

    @classmethod
    def _background_task_response(
        cls,
        task: str,
        body: dict[str, Any],
        explicit_task_body: Any,
        explicit_metadata: Any,
    ) -> str:
        if task not in SAFE_BACKGROUND_TASKS:
            raise RuntimeError(f'Material Graph refuses unsupported Open WebUI background task: {task}')

        metadata = body.get('metadata')
        metadata = metadata if isinstance(metadata, dict) else {}
        explicit_metadata = explicit_metadata if isinstance(explicit_metadata, dict) else {}
        task_body = explicit_task_body
        if not isinstance(task_body, dict):
            task_body = explicit_metadata.get('task_body')
        if not isinstance(task_body, dict):
            task_body = metadata.get('task_body')

        if task == TITLE_GENERATION:
            value = {'title': cls._deterministic_title(task_body, body)}
        elif task == TAGS_GENERATION:
            value = {'tags': []}
        elif task == FOLLOW_UP_GENERATION:
            value = {'follow_ups': []}
        else:
            raise AssertionError(f'unhandled safe background task: {task}')
        return json.dumps(value, ensure_ascii=False, separators=(',', ':'))

    async def pipe(  # noqa: C901 - background-task guard and streaming transport share this boundary
        self,
        body: dict[str, Any],
        __event_emitter__=None,
        __user__=None,
        __task__=None,
        __task_body__=None,
        __metadata__=None,
        **_: Any,
    ) -> AsyncIterator[str]:
        background_task = self._background_task_name(body, __task__, __metadata__)
        if background_task is not None:
            yield self._background_task_response(
                background_task,
                body,
                __task_body__,
                __metadata__,
            )
            return

        messages = body.get('messages') or []
        message = next(
            (
                self._content_text(item.get('content'))
                for item in reversed(messages)
                if isinstance(item, dict) and item.get('role') == 'user'
            ),
            '',
        )
        payload = {
            'message': message,
            'scenario': body.get('scenario') or self.valves.scenario,
            'auto_approve': False,
            'history': self._conversation_history(messages),
        }
        conversation_id = self._conversation_id(body, __metadata__)
        if conversation_id is not None:
            payload['conversation_id'] = conversation_id
            conversation_state = self._cached_conversation_state(conversation_id)
            if conversation_state is not None:
                payload['conversation_state'] = conversation_state
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
        assistant_delta_runs: set[str | None] = set()
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
                            assistant_delta_runs=assistant_delta_runs,
                            expected_conversation_id=conversation_id,
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
                        assistant_delta_runs=assistant_delta_runs,
                        expected_conversation_id=conversation_id,
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
        if (
            kind in TERMINAL
            and action != 'material_graph'
            and data.get('mode') in {'knowledge_answer', 'research_discussion'}
        ):
            return None
        if kind == KNOWLEDGE_SIGNAL:
            if not run:
                return None
            return {
                **data,
                'action': 'material_graph_knowledge',
                'run_id': str(run),
                'type': data.get('type') or name or KNOWLEDGE_SIGNAL,
                'event_type': data.get('event_type') or KNOWLEDGE_SIGNAL,
                'contract_version': (version or data.get('contract_version') or 'legacy'),
            }
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
        assistant_delta_runs: set[str | None] | None = None,
        expected_conversation_id: str | None = None,
    ) -> AsyncIterator[str]:
        name, version, data = self._payload(event)
        self._remember_conversation_state(expected_conversation_id, name, data)
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
            content_mode = str(data.get('content_mode') or event.get('content_mode') or '').lower()
            is_final = name == 'assistant_message' or content_mode == 'final'
            raw_run_id = data.get('run_id') or data.get('runId') or event.get('run_id') or event.get('runId')
            run_id = str(raw_run_id) if raw_run_id is not None else None
            if not (is_final and assistant_delta_runs is not None and run_id in assistant_delta_runs):
                yield str(token)
            if not is_final and name in TOKEN and assistant_delta_runs is not None:
                assistant_delta_runs.add(run_id)
        error = event.get('error') or data.get('error')
        if error:
            raise RuntimeError(str(error))
