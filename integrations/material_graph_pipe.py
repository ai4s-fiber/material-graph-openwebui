"""Version-compatible Material Graph Pipe for Open WebUI v0.10.2."""

from __future__ import annotations
import json
from typing import Any, AsyncIterator
import httpx
from pydantic import BaseModel, Field

GRAPH = {'workflowdefinition', 'workflow_definition', 'workflow', 'graph'}
NODE = {'nodestate', 'node_state', 'node_status', 'node'}
TOKEN = {'token', 'text_delta', 'delta', 'assistant_token'}
TOKEN = TOKEN | {'assistant_delta', 'assistant_message'}
LOG = {'log', 'workflow_log', 'node_log'}
FORM = {'assistant_form', 'assistantform', 'form'}
TERMINAL = {'terminal', 'terminal_outcome', 'outcome', 'run_completed', 'run_terminal'}
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
        timeout_seconds: float = Field(default=180.0, ge=5.0, le=1800.0)
        scenario: str = Field(default='generic_material')

    def __init__(self):
        self.name = 'Material Graph Studio'
        self.valves = self.Valves()
        self._runs = {}
        self._assistant_text = {}

    async def pipe(self, body: dict[str, Any], __event_emitter__=None, **_: Any) -> AsyncIterator[str]:
        messages = body.get('messages') or []
        message = next((str(x.get('content', '')) for x in reversed(messages) if x.get('role') == 'user'), '')
        payload = {'message': message, 'scenario': body.get('scenario') or self.valves.scenario, 'auto_approve': False}
        if isinstance(body.get('material_graph_task'), dict):
            payload['task'] = body['material_graph_task']
        base = self.valves.material_graph_api_url.rstrip('/')
        async with httpx.AsyncClient(timeout=httpx.Timeout(self.valves.timeout_seconds, connect=15.0)) as client:
            async with client.stream('POST', f'{base}/chat/stream', json=payload) as response:
                response.raise_for_status()
                lines = []
                async for line in response.aiter_lines():
                    if line.startswith('data:'):
                        lines.append(line[5:].lstrip())
                    elif not line and lines:
                        async for token in self._forward_event(json.loads('\n'.join(lines)), base, __event_emitter__):
                            yield token
                        lines = []
                if lines:
                    async for token in self._forward_event(json.loads('\n'.join(lines)), base, __event_emitter__):
                        yield token

    @staticmethod
    def _payload(event):
        version = event.get('version') or event.get('schema_version')
        envelope = event.get('event')
        if isinstance(envelope, dict) and envelope.get('type') == 'status' and isinstance(envelope.get('data'), dict):
            return 'status', str(version) if version is not None else None, envelope['data']
        source = envelope if isinstance(envelope, dict) else event
        version = source.get('version') or source.get('schema_version') or version
        name = source.get('type') or source.get('event_type') or event.get('type') or ''
        data = source.get('data') or source.get('payload')
        return (
            str(name).lower(),
            str(version) if version is not None else None,
            data if isinstance(data, dict) else source,
        )

    def _status(self, name, version, data, base):
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
            kind = str(data.get('event_type') or 'graph').lower()
        if kind not in GRAPH | NODE | LOG | TERMINAL and action != 'material_graph':
            return None
        if not run:
            return None
        state = self._runs.setdefault(str(run), {'nodes': [], 'edges': [], 'logs': []})
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
                nodes.append({**node, 'id': node_id, 'label': node.get('label') or str(node_id), 'status': node_status})
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
        outcome = (
            (outcome.get('status') or outcome.get('outcome') or outcome.get('type'))
            if isinstance(outcome, dict)
            else outcome
        )
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
        ):
            if source in data:
                state[target] = data[source]
        if 'done' in data:
            state['done'] = bool(data['done'])
        if 'success' in data:
            state['success'] = bool(data['success'])
        state['contract_version'] = version or data.get('contract_version') or state.get('contract_version') or 'legacy'
        return {'action': 'material_graph', 'run_id': str(run), **state}

    async def _forward_event(self, event, base_url, emitter):
        name, version, data = self._payload(event)
        version = version or event.get('contract_version')
        status = self._status(name, version, data, base_url)
        if status is not None and emitter is not None:
            await emitter({'type': 'status', 'data': status})
        elif name == 'status' and emitter is not None and isinstance(event.get('event'), dict):
            await emitter(event['event'])
        if name in {'assistant_delta', 'assistant_message'}:
            run = data.get('run_id') or data.get('runId')
            run_key = str(run) if run else None
            if name == 'assistant_delta':
                token = data.get('delta') or data.get('token')
                if token and run_key:
                    previous = self._assistant_text.get(run_key)
                    if previous is None and run_key in self._assistant_text:
                        token = None
                    else:
                        token = str(token)
                        self._assistant_text[run_key] = f'{previous or ""}{token}'
                elif token:
                    token = str(token)
            else:
                token = data.get('content') or data.get('delta')
                if token and run_key:
                    token = str(token)
                    if run_key in self._assistant_text:
                        previous = self._assistant_text[run_key]
                        self._assistant_text[run_key] = None
                        if previous is None:
                            token = None
                        elif token.startswith(previous):
                            token = token[len(previous) :] or None
                        else:
                            token = None
                    else:
                        self._assistant_text[run_key] = None
                elif token:
                    token = str(token)
            if token:
                yield str(token)
            error = event.get('error') or data.get('error')
            if error:
                raise RuntimeError(str(error))
            return
        token = event.get('delta') or event.get('token')
        if not token and name in TOKEN:
            token = data.get('delta') or data.get('token') or data.get('text') or data.get('content')
        if token:
            yield str(token)
        error = event.get('error') or data.get('error')
        if error:
            raise RuntimeError(str(error))
