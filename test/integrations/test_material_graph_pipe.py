from __future__ import annotations

import asyncio
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'integrations'))
import material_graph_pipe as pipe_module  # noqa: E402
from material_graph_pipe import Pipe  # noqa: E402
from open_webui.utils.material_graph_auth import load_material_graph_hmac_secret  # noqa: E402


class ManualClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def set(self, value):
        self.value = float(value)


def graph_snapshot(run_id, *, graph_version=1):
    return {
        'action': 'material_graph',
        'event_type': 'graph_snapshot',
        'run_id': run_id,
        'graph_version': graph_version,
        'nodes': [{'id': 'intake', 'label': 'Intake', 'status': 'running'}],
        'edges': [],
        'logs': [],
        'done': False,
    }


async def forward(
    pipe,
    event,
    client=None,
    *,
    resync_base_url=None,
    auth_headers=None,
    expected_conversation_id=None,
):
    emitted = []

    async def emitter(item):
        emitted.append(item)

    return [
        x
        async for x in pipe._forward_event(
            event,
            'https://material.example/api',
            emitter,
            client=client,
            resync_base_url=resync_base_url,
            auth_headers=auth_headers,
            expected_conversation_id=expected_conversation_id,
        )
    ], emitted


def test_legacy_graph_and_token():
    tokens, events = asyncio.run(
        forward(
            Pipe(),
            {
                'delta': '真流式',
                'event': {
                    'type': 'status',
                    'data': {
                        'action': 'material_graph',
                        'run_id': 'r1',
                        'nodes': [{'id': 'any', 'label': '任意'}],
                        'edges': [],
                    },
                },
            },
        )
    )
    assert tokens == ['真流式']
    assert events[0]['data']['nodes'][0]['id'] == 'any'
    assert events[0]['data']['contract_version'] == 'legacy'


def test_versioned_form_endpoint():
    _, events = asyncio.run(
        forward(
            Pipe(),
            {
                'version': '2.0',
                'event': {
                    'type': 'assistant_form',
                    'data': {'formId': 'equipment', 'runId': 'r2', 'schema': {'type': 'object'}},
                },
            },
        )
    )
    form = events[0]['data']
    assert form['form_id'] == 'equipment'
    assert form['endpoint'] == 'https://material.example/api'
    assert form['contract_version'] == '2.0'


def test_full_workflow_survives_partial_events():
    pipe = Pipe()
    asyncio.run(
        forward(
            pipe,
            {
                'version': '2',
                'event': {
                    'type': 'WorkflowDefinition',
                    'data': {
                        'runId': 'r3',
                        'workflow': {
                            'nodes': [{'id': 'intake', 'label': 'Intake'}, {'id': 'gate', 'label': 'Gate'}],
                            'edges': [{'source': 'intake', 'target': 'gate'}],
                        },
                    },
                },
            },
        )
    )
    asyncio.run(
        forward(
            pipe,
            {
                'event': {
                    'type': 'NodeState',
                    'data': {'run_id': 'r3', 'node_id': 'gate', 'status': 'awaiting_review', 'authoritative': True},
                }
            },
        )
    )
    _, events = asyncio.run(
        forward(
            pipe,
            {'event': {'type': 'log', 'data': {'run_id': 'r3', 'node_id': 'gate', 'message': 'checkpoint persisted'}}},
        )
    )
    graph = events[0]['data']
    assert len(graph['nodes']) == 2
    assert graph['current_node'] == 'gate'
    assert graph['logs'][0]['message'] == 'checkpoint persisted'


def test_knowledge_signal_is_forwarded_without_mutating_execution_graph():
    pipe = Pipe()
    workflow_nodes = [{'id': f'node-{index}', 'label': f'Node {index}', 'status': 'pending'} for index in range(15)]
    workflow_edges = [{'source': f'node-{index}', 'target': f'node-{index + 1}'} for index in range(14)] + [
        {'source': f'node-{index}', 'target': f'node-{index + 2}'} for index in range(10)
    ]
    asyncio.run(
        forward(
            pipe,
            {
                'contract_version': 'material-graph.sse.v2',
                'type': 'graph_snapshot',
                'event_type': 'graph_snapshot',
                'action': 'material_graph',
                'run_id': 'run-knowledge',
                'graph_version': 1,
                'nodes': workflow_nodes,
                'edges': workflow_edges,
                'logs': [],
            },
        )
    )
    knowledge_nodes = [
        {
            'id': 'kg-polyimide',
            'label': '聚酰亚胺',
            'agent_roles': ['material'],
            'hit': True,
        },
        {
            'id': 'kg-tg',
            'label': '玻璃化转变温度',
            'agent_roles': ['performance_testing'],
            'hit': True,
        },
    ]
    knowledge_edges = [
        {
            'id': 'kg-edge-1',
            'source': 'kg-polyimide',
            'target': 'kg-tg',
            'relation': 'has_property',
        }
    ]
    pulse = [
        {
            'edge_id': 'kg-edge-1',
            'source': 'kg-polyimide',
            'target': 'kg-tg',
        }
    ]
    stats = {
        'total_nodes': 2,
        'total_edges': 1,
        'visible_nodes': 2,
        'visible_edges': 1,
        'truncated': False,
    }

    _, events = asyncio.run(
        forward(
            pipe,
            {
                'contract_version': 'material-graph.sse.v2',
                'type': 'knowledge_signal',
                'event_type': 'knowledge_signal',
                'action': 'material_graph',
                'signal_version': 1,
                'run_id': 'run-knowledge',
                'phase': 'agent_execution',
                'workflow_node': 'material_design',
                'graph_id': 'task-graph-run-knowledge',
                'graph_version_label': 'V2',
                'nodes': knowledge_nodes,
                'edges': knowledge_edges,
                'pulse': pulse,
                'stats': stats,
                'active_agents': ['material', 'performance_testing'],
            },
        )
    )

    signal = events[0]['data']
    assert signal['action'] == 'material_graph_knowledge'
    assert signal['run_id'] == 'run-knowledge'
    assert signal['type'] == 'knowledge_signal'
    assert signal['event_type'] == 'knowledge_signal'
    assert signal['signal_version'] == 1
    assert signal['phase'] == 'agent_execution'
    assert signal['workflow_node'] == 'material_design'
    assert signal['graph_id'] == 'task-graph-run-knowledge'
    assert signal['graph_version_label'] == 'V2'
    assert signal['nodes'] == knowledge_nodes
    assert signal['edges'] == knowledge_edges
    assert signal['pulse'] == pulse
    assert signal['stats'] == stats
    assert signal['active_agents'] == ['material', 'performance_testing']
    assert len(pipe._runs['run-knowledge']['nodes']) == 15
    assert len(pipe._runs['run-knowledge']['edges']) == 24
    assert pipe._runs['run-knowledge']['nodes'] == workflow_nodes
    assert pipe._runs['run-knowledge']['edges'] == workflow_edges

    tokens, no_signal_events = asyncio.run(
        forward(
            pipe,
            {
                'type': 'assistant_delta',
                'event_type': 'assistant_delta',
                'run_id': 'run-knowledge',
                'delta': '继续执行',
            },
        )
    )
    assert tokens == ['继续执行']
    assert no_signal_events == []


def test_v2_knowledge_signal_without_action_is_forwarded():
    _, events = asyncio.run(
        forward(
            Pipe(),
            {
                'contract_version': 'material-graph.sse.v2',
                'type': 'knowledge_signal',
                'event_type': 'knowledge_signal',
                'run_id': 'conversation-chat-1234',
                'signal_version': 1,
                'nodes': [{'id': 'evidence:E1', 'type': 'evidence'}],
                'edges': [
                    {
                        'id': 'provenance:E1:S1',
                        'source': 'evidence:E1',
                        'target': 'source:S1',
                        'predicate': 'provenance',
                    }
                ],
            },
        )
    )

    assert events == [
        {
            'type': 'status',
            'data': {
                'contract_version': 'material-graph.sse.v2',
                'type': 'knowledge_signal',
                'event_type': 'knowledge_signal',
                'action': 'material_graph_knowledge',
                'run_id': 'conversation-chat-1234',
                'signal_version': 1,
                'nodes': [{'id': 'evidence:E1', 'type': 'evidence'}],
                'edges': [
                    {
                        'id': 'provenance:E1:S1',
                        'source': 'evidence:E1',
                        'target': 'source:S1',
                        'predicate': 'provenance',
                    }
                ],
            },
        }
    ]


def test_conversation_done_caches_state_without_emitting_empty_workflow_status():
    pipe = Pipe()
    conversation_state = {
        'schema': 'material_graph.conversation_state.v1',
        'mode': 'research_discussion',
        'task_state': {'material_family': 'PI'},
    }

    tokens, events = asyncio.run(
        forward(
            pipe,
            {
                'contract_version': 'material-graph.sse.v2',
                'type': 'done',
                'event_type': 'done',
                'run_id': 'chat-1234',
                'conversation_id': 'chat-1234',
                'mode': 'research_discussion',
                'conversation_state': conversation_state,
                'done': True,
            },
            expected_conversation_id='chat-1234',
        )
    )

    assert tokens == []
    assert events == []
    assert pipe._cached_conversation_state('chat-1234') == conversation_state
    assert 'chat-1234' not in pipe._runs


def test_token_and_non_success_terminal():
    pipe = Pipe()
    tokens, _ = asyncio.run(
        forward(
            pipe,
            {'schema_version': '2.1', 'event_type': 'assistant_token', 'payload': {'run_id': 'r4', 'text': '逐 token'}},
        )
    )
    assert tokens == ['逐 token']
    _, events = asyncio.run(
        forward(
            pipe,
            {
                'event': {
                    'type': 'terminal_outcome',
                    'data': {'run_id': 'r4', 'outcome': {'status': 'budget_stopped'}, 'current_node': 'rank'},
                }
            },
        )
    )
    terminal = events[0]['data']
    assert terminal['done'] is True
    assert terminal['success'] is False
    assert terminal['outcome'] == 'budget_stopped'


def test_graph_overload_terminal_preserves_stable_retry_contract():
    pipe = Pipe()
    status = pipe._status(
        'error',
        'material-graph.sse.v2',
        {
            'action': 'material_graph',
            'event_type': 'terminal',
            'run_id': 'r-overload',
            'outcome': 'error',
            'done': True,
            'success': False,
            'error_code': 'graph_admission.queue_full',
            'retryable': True,
            'retry_after_seconds': 7,
        },
        'https://material.example/api',
    )

    assert status is not None
    assert status['error_code'] == 'graph_admission.queue_full'
    assert status['retryable'] is True
    assert status['retry_after_seconds'] == 7


def test_non_authoritative_event_does_not_move_current_node():
    pipe = Pipe()
    asyncio.run(
        forward(
            pipe, {'event': {'type': 'node_state', 'data': {'run_id': 'r5', 'node_id': 'first', 'status': 'running'}}}
        )
    )
    _, events = asyncio.run(
        forward(
            pipe,
            {
                'event': {
                    'type': 'node_state',
                    'data': {'run_id': 'r5', 'node_id': 'background', 'status': 'running', 'authoritative': False},
                }
            },
        )
    )
    assert events[0]['data']['current_node'] == 'first'


def test_v2_snapshot_and_delta_reconstruct_one_authoritative_status():
    pipe = Pipe()
    snapshot = {
        'contract_version': 'material-graph.sse.v2',
        'type': 'graph_snapshot',
        'event_type': 'graph_snapshot',
        'action': 'material_graph',
        'run_id': 'r6',
        'graph_version': 1,
        'current_node': 'intake',
        'nodes': [
            {'id': 'intake', 'label': 'Intake', 'status': 'running'},
            {'id': 'gate', 'label': 'Gate', 'status': 'pending'},
        ],
        'edges': [{'source': 'intake', 'target': 'gate'}],
        'logs': [],
    }
    asyncio.run(forward(pipe, snapshot))
    delta = {
        'contract_version': 'material-graph.sse.v2',
        'type': 'graph_delta',
        'event_type': 'graph_delta',
        'action': 'material_graph',
        'run_id': 'r6',
        'base_version': 1,
        'graph_version': 2,
        'patch': {
            'set': {'current_node': 'gate', 'elapsed_ms': 800},
            'node_updates': [
                {'id': 'intake', 'label': 'Intake', 'status': 'complete'},
                {'id': 'gate', 'label': 'Gate', 'status': 'running'},
            ],
            'logs': [{'node_id': 'intake', 'message': 'done'}],
        },
        'resync_url': '/runs/r6/graph',
    }

    _, events = asyncio.run(forward(pipe, delta))

    graph = events[0]['data']
    assert graph['graph_version'] == 2
    assert graph['current_node'] == 'gate'
    assert [node['status'] for node in graph['nodes']] == ['complete', 'running']
    assert graph['logs'][0]['message'] == 'done'
    assert graph['resync_required'] is False


def test_version_gap_fetches_authoritative_resync_snapshot():
    pipe = Pipe()
    asyncio.run(
        forward(
            pipe,
            {
                'contract_version': 'material-graph.sse.v2',
                'type': 'graph_snapshot',
                'event_type': 'graph_snapshot',
                'action': 'material_graph',
                'run_id': 'r7',
                'graph_version': 1,
                'nodes': [{'id': 'intake', 'label': 'Intake', 'status': 'running'}],
                'edges': [],
                'logs': [],
            },
        )
    )
    gap = {
        'contract_version': 'material-graph.sse.v2',
        'type': 'graph_delta',
        'event_type': 'graph_delta',
        'action': 'material_graph',
        'run_id': 'r7',
        'base_version': 2,
        'graph_version': 3,
        'patch': {'set': {'current_node': 'gate'}},
        'resync_url': '/runs/r7/graph',
    }

    async def scenario():
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == '/api/runs/r7/graph'
            return httpx.Response(
                200,
                json={
                    'contract_version': 'material-graph.sse.v2',
                    'type': 'graph_snapshot',
                    'event_type': 'graph_snapshot',
                    'action': 'material_graph',
                    'snapshot_reason': 'resync',
                    'run_id': 'r7',
                    'graph_version': 3,
                    'current_node': 'gate',
                    'nodes': [
                        {'id': 'intake', 'label': 'Intake', 'status': 'complete'},
                        {'id': 'gate', 'label': 'Gate', 'status': 'running'},
                    ],
                    'edges': [],
                    'logs': [],
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await forward(pipe, gap, client)

    _, events = asyncio.run(scenario())
    graph = events[0]['data']
    assert graph['graph_version'] == 3
    assert graph['current_node'] == 'gate'
    assert graph['resync_required'] is False


def test_version_gap_resync_signs_query_bound_get():
    pipe = Pipe()
    asyncio.run(
        forward(
            pipe,
            {
                'contract_version': 'material-graph.sse.v2',
                'event_type': 'graph_snapshot',
                'action': 'material_graph',
                'run_id': 'r8',
                'graph_version': 1,
                'nodes': [],
                'edges': [],
                'logs': [],
            },
        )
    )
    gap = {
        'contract_version': 'material-graph.sse.v2',
        'event_type': 'graph_delta',
        'action': 'material_graph',
        'run_id': 'r8',
        'base_version': 2,
        'graph_version': 3,
        'patch': {'set': {'current_node': 'gate'}},
        'resync_url': '/runs/r8/graph',
    }
    signed_targets = []

    def auth_headers(method, target):
        signed_targets.append((method, target))
        return {'X-Material-Graph-User-Context': 'signed-resync'}

    async def scenario():
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.host == 'material-graph-api'
            assert request.url.path == '/runs/r8/graph'
            assert request.url.query == b'known_version=1'
            assert request.headers['X-Material-Graph-User-Context'] == 'signed-resync'
            return httpx.Response(
                200,
                json={
                    'contract_version': 'material-graph.sse.v2',
                    'event_type': 'graph_snapshot',
                    'action': 'material_graph',
                    'run_id': 'r8',
                    'graph_version': 3,
                    'current_node': 'gate',
                    'nodes': [],
                    'edges': [],
                    'logs': [],
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await forward(
                pipe,
                gap,
                client,
                resync_base_url='http://material-graph-api:8000',
                auth_headers=auth_headers,
            )

    _, events = asyncio.run(scenario())
    assert signed_targets == [('GET', '/runs/r8/graph?known_version=1')]
    assert events[0]['data']['graph_version'] == 3


def test_pipe_signs_authenticated_user_and_uses_same_origin_resume_proxy(  # noqa: C901
    monkeypatch, tmp_path
):
    secret = b'pipe-test-material-graph-hmac-secret-32-bytes'
    secret_file = tmp_path / 'hmac-secret'
    secret_file.write_bytes(secret)
    monkeypatch.setenv('MATERIAL_GRAPH_HMAC_SECRET_FILE', str(secret_file))
    load_material_graph_hmac_secret.cache_clear()
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        async def aiter_lines(self):
            yield 'data: ' + json.dumps(
                {
                    'delta': 'ok',
                    'event': {
                        'type': 'status',
                        'data': {
                            'action': 'assistant_form',
                            'run_id': 'r-auth',
                            'form_id': 'review',
                        },
                    },
                }
            )
            yield ''

    class Stream:
        async def __aenter__(self):
            return Response()

        async def __aexit__(self, *_):
            return None

    class Client:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        def stream(self, method, url, **kwargs):
            captured.update(method=method, url=url, **kwargs)
            return Stream()

    monkeypatch.setattr(pipe_module.httpx, 'AsyncClient', Client)
    pipe = Pipe()
    emitted = []

    async def emitter(item):
        emitted.append(item)

    async def run():
        return [
            item
            async for item in pipe.pipe(
                {
                    'messages': [
                        {'role': 'system', 'content': 'private system prompt'},
                        {'role': 'user', 'content': 'Earlier question'},
                        {'role': 'assistant', 'content': 'Earlier answer'},
                        {
                            'role': 'user',
                            'content': [
                                {'type': 'text', 'text': 'design'},
                                {'type': 'image_url', 'image_url': {'url': 'https://private.example/image'}},
                            ],
                        },
                    ]
                },
                __event_emitter__=emitter,
                __user__={'id': 'user-12345678', 'role': 'user'},
                __metadata__={'chat_id': 'chat-1234'},
            )
        ]

    assert asyncio.run(run()) == ['ok']
    assert captured['url'].endswith('/chat/stream')
    assert 'X-Material-Graph-User-Context' in captured['headers']
    payload = json.loads(captured['content'])
    assert payload == {
        'message': 'design',
        'scenario': 'custom',
        'auto_approve': False,
        'history': [
            {'role': 'user', 'content': 'Earlier question'},
            {'role': 'assistant', 'content': 'Earlier answer'},
        ],
        'conversation_id': 'chat-1234',
    }
    assert emitted[0]['data']['endpoint'] == '/api/v1/material-graph'
    load_material_graph_hmac_secret.cache_clear()


def test_pipe_reuses_only_bounded_conversation_state_for_the_same_chat(monkeypatch):  # noqa: C901
    monkeypatch.setattr(pipe_module, 'build_material_graph_auth_headers', lambda **_: {})
    posted_payloads = []
    response_events = [
        [
            {
                'contract_version': 'material-graph.sse.v2',
                'type': 'assistant_message',
                'event_type': 'assistant_message',
                'run_id': 'chat-1234',
                'conversation_id': 'chat-1234',
                'content_mode': 'final',
                'content': '请继续补充目标。',
            },
            {
                'contract_version': 'material-graph.sse.v2',
                'type': 'done',
                'event_type': 'done',
                'run_id': 'chat-1234',
                'conversation_id': 'chat-1234',
                'status': 'completed',
                'files': [{'url': 'https://private.example/result'}],
                'conversation_state': {
                    'schema': 'material_graph.conversation_state.v1',
                    'mode': 'research_discussion',
                    'task_state': {
                        'material_family': 'PI',
                        'status': {'secret': 'must not be cached'},
                        'files': [{'url': 'https://private.example/source'}],
                    },
                },
                'done': True,
            },
        ],
        [],
        [],
    ]

    class Response:
        def __init__(self, events):
            self.events = events

        def raise_for_status(self):
            return None

        async def aiter_lines(self):
            for event in self.events:
                yield f'data: {json.dumps(event, ensure_ascii=False)}'
                yield ''

    class Stream:
        def __init__(self, events):
            self.response = Response(events)

        async def __aenter__(self):
            return self.response

        async def __aexit__(self, *_):
            return None

    class Client:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        def stream(self, _method, _url, **kwargs):
            posted_payloads.append(json.loads(kwargs['content']))
            return Stream(response_events.pop(0))

    monkeypatch.setattr(pipe_module.httpx, 'AsyncClient', Client)
    pipe = Pipe()
    user = {'id': 'user-12345678', 'role': 'user'}

    async def invoke(chat_id, messages):
        return [
            item
            async for item in pipe.pipe(
                {'messages': messages},
                __user__=user,
                __metadata__={'chat_id': chat_id},
            )
        ]

    first_messages = [{'role': 'user', 'content': '我想做 PI 材料'}]
    assert asyncio.run(invoke('chat-1234', first_messages)) == ['请继续补充目标。']

    second_messages = [
        *first_messages,
        {'role': 'assistant', 'content': '请继续补充目标。'},
        {'role': 'user', 'content': '继续'},
    ]
    assert asyncio.run(invoke('chat-1234', second_messages)) == []
    assert asyncio.run(invoke('chat-other', second_messages)) == []

    assert 'conversation_state' not in posted_payloads[0]
    assert posted_payloads[1]['conversation_state'] == {
        'schema': 'material_graph.conversation_state.v1',
        'mode': 'research_discussion',
        'task_state': {'material_family': 'PI'},
    }
    assert 'conversation_state' not in posted_payloads[2]
    assert 'private.example' not in json.dumps(posted_payloads[1], ensure_ascii=False)
    assert all(key not in posted_payloads[1] for key in ('status', 'files'))


def test_conversation_context_is_recent_plain_text_and_bounded():
    pipe = Pipe()
    messages = [
        {'role': 'system', 'content': 'must never be forwarded'},
        *[
            {
                'role': 'user' if index % 2 == 0 else 'assistant',
                'content': [
                    {'type': 'text', 'text': f'context-{index}'},
                    {'type': 'image_url', 'image_url': {'url': f'https://private.example/{index}'}},
                ],
                'statusHistory': [{'secret': 'must not leak'}],
            }
            for index in range(30)
        ],
        {'role': 'user', 'content': 'current request'},
    ]

    history = pipe._conversation_history(messages)

    assert len(history) == 24
    assert history[0] == {'role': 'user', 'content': 'context-6'}
    assert history[-1] == {'role': 'assistant', 'content': 'context-29'}
    assert all(set(item) == {'role', 'content'} for item in history)
    assert all('private.example' not in item['content'] for item in history)
    assert all(len(item['content']) <= pipe_module.HISTORY_MAX_CONTENT_CHARS for item in history)
    assert sum(len(item['content'].encode('utf-8')) for item in history) <= pipe_module.HISTORY_MAX_CONTENT_BYTES


@pytest.mark.parametrize(
    ('chat_id', 'expected'),
    [
        ('chat-1234', 'chat-1234'),
        (' local:session_1 ', 'local:session_1'),
        ('contains whitespace', None),
        ('../unsafe', None),
        ('x' * 129, None),
    ],
)
def test_conversation_id_is_safe_and_bounded(chat_id, expected):
    assert Pipe._conversation_id({}, {'chat_id': chat_id}) == expected


def test_conversation_history_enforces_utf8_byte_budget():
    history = Pipe._conversation_history(
        [
            *[
                {
                    'role': 'assistant',
                    'content': '高' * pipe_module.HISTORY_MAX_CONTENT_CHARS,
                }
                for _ in range(24)
            ],
            {'role': 'user', 'content': 'current request'},
        ]
    )

    assert all(len(item['content']) <= pipe_module.HISTORY_MAX_CONTENT_CHARS for item in history)
    assert sum(len(item['content'].encode('utf-8')) for item in history) <= pipe_module.HISTORY_MAX_CONTENT_BYTES


def test_explicit_demo_scenario_is_forwarded_without_becoming_the_default(monkeypatch):  # noqa: C901
    captured = []
    monkeypatch.setattr(pipe_module, 'build_material_graph_auth_headers', lambda **_: {})

    class Response:
        def raise_for_status(self):
            return None

        async def aiter_lines(self):
            if False:
                yield ''

    class Stream:
        async def __aenter__(self):
            return Response()

        async def __aexit__(self, *_):
            return None

    class Client:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        def stream(self, _method, _url, **kwargs):
            captured.append(json.loads(kwargs['content']))
            return Stream()

    monkeypatch.setattr(pipe_module.httpx, 'AsyncClient', Client)
    pipe = Pipe()

    async def run(scenario):
        return [
            token
            async for token in pipe.pipe(
                {
                    'messages': [{'role': 'user', 'content': 'run demo'}],
                    'scenario': scenario,
                },
                __user__={'id': 'user-12345678', 'role': 'user'},
            )
        ]

    for scenario in ('polyimide_design', 'pet_pa6_melt_spinning'):
        assert asyncio.run(run(scenario)) == []

    assert [payload['scenario'] for payload in captured] == [
        'polyimide_design',
        'pet_pa6_melt_spinning',
    ]


def test_one_user_turn_posts_graph_once_and_background_tasks_never_post(  # noqa: C901
    monkeypatch,
):
    graph_posts = []
    monkeypatch.setattr(pipe_module, 'build_material_graph_auth_headers', lambda **_: {})

    class Response:
        def raise_for_status(self):
            return None

        async def aiter_lines(self):
            if False:
                yield ''

    class Stream:
        async def __aenter__(self):
            return Response()

        async def __aexit__(self, *_):
            return None

    class Client:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        def stream(self, method, url, **kwargs):
            graph_posts.append((method, url, json.loads(kwargs['content'])))
            return Stream()

    monkeypatch.setattr(pipe_module.httpx, 'AsyncClient', Client)
    pipe = Pipe()
    user = {'id': 'user-12345678', 'role': 'user'}
    original_messages = [
        {
            'role': 'user',
            'content': '请设计一种高 Tg 的聚酰亚胺，并给出实验安排。',
        }
    ]

    async def invoke(body, **kwargs):
        return [item async for item in pipe.pipe(body, __user__=user, **kwargs)]

    assert (
        asyncio.run(
            invoke(
                {
                    'messages': original_messages,
                }
            )
        )
        == []
    )
    title = asyncio.run(
        invoke(
            {
                'messages': [{'role': 'user', 'content': 'generated title prompt'}],
                'metadata': {
                    'task': 'title_generation',
                    'task_body': {'messages': original_messages},
                },
            },
        )
    )
    tags = asyncio.run(
        invoke(
            {'messages': [{'role': 'user', 'content': 'generated tags prompt'}]},
            __task__='tags_generation',
            __task_body__={'messages': original_messages},
        )
    )
    follow_ups = asyncio.run(
        invoke(
            {'messages': [{'role': 'user', 'content': 'generated follow-up prompt'}]},
            __task__='follow_up_generation',
            __task_body__={'messages': original_messages},
        )
    )

    assert len(graph_posts) == 1
    assert graph_posts[0][0] == 'POST'
    assert graph_posts[0][1].endswith('/chat/stream')
    assert json.loads(''.join(title)) == {'title': '请设计一种高 Tg 的聚酰亚胺，并给出实验安排。'}
    assert json.loads(''.join(tags)) == {'tags': []}
    assert json.loads(''.join(follow_ups)) == {'follow_ups': []}


def test_body_metadata_task_is_fail_closed_before_auth_or_network(monkeypatch):
    client_created = False

    class Client:
        def __init__(self, **_):
            nonlocal client_created
            client_created = True

    monkeypatch.setattr(pipe_module.httpx, 'AsyncClient', Client)
    pipe = Pipe()

    async def invoke():
        return [
            item
            async for item in pipe.pipe(
                {
                    'messages': [{'role': 'user', 'content': 'background prompt'}],
                    'metadata': {'task': 'query_generation'},
                }
            )
        ]

    with pytest.raises(RuntimeError, match='background task'):
        asyncio.run(invoke())
    assert client_created is False


def test_material_graph_shell_disables_nonessential_background_tasks_by_default():
    dockerfile = (ROOT / 'Dockerfile').read_text(encoding='utf-8')

    assert 'ENABLE_FOLLOW_UP_GENERATION=false' in dockerfile
    assert 'ENABLE_TAGS_GENERATION=false' in dockerfile


def test_pipe_deduplicates_stream_final_per_call_and_preserves_final_only(  # noqa: C901
    monkeypatch,
):
    monkeypatch.setattr(pipe_module, 'build_material_graph_auth_headers', lambda **_: {})
    response_events = [
        [
            {
                'type': 'assistant_delta',
                'event_type': 'assistant_delta',
                'run_id': 'r-stream',
                'content_mode': 'incremental',
                'delta': '你好',
            },
            {
                'type': 'assistant_delta',
                'event_type': 'assistant_delta',
                'run_id': 'r-stream',
                'content_mode': 'incremental',
                'delta': '，我是材料研发助手。',
            },
            {
                'type': 'assistant_message',
                'event_type': 'assistant_message',
                'run_id': 'r-stream',
                'content_mode': 'final',
                'content': '你好，我是材料研发助手。',
                'delta': '你好，我是材料研发助手。',
            },
        ],
        [
            {
                'type': 'assistant_message',
                'event_type': 'assistant_message',
                'run_id': 'r-stream',
                'content_mode': 'final',
                'content': '这是下一次调用的完整回答。',
                'delta': '这是下一次调用的完整回答。',
            }
        ],
    ]

    class Response:
        def __init__(self, events):
            self.events = events

        def raise_for_status(self):
            return None

        async def aiter_lines(self):
            for event in self.events:
                yield f'data: {json.dumps(event, ensure_ascii=False)}'
                yield ''

    class Stream:
        def __init__(self, events):
            self.response = Response(events)

        async def __aenter__(self):
            return self.response

        async def __aexit__(self, *_):
            return None

    class Client:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        def stream(self, _method, _url, **_):
            return Stream(response_events.pop(0))

    monkeypatch.setattr(pipe_module.httpx, 'AsyncClient', Client)
    pipe = Pipe()

    async def run():
        return [
            token
            async for token in pipe.pipe(
                {'messages': [{'role': 'user', 'content': '你好'}]},
                __user__={'id': 'user-12345678', 'role': 'user'},
            )
        ]

    assert asyncio.run(run()) == ['你好', '，我是材料研发助手。']
    assert asyncio.run(run()) == ['这是下一次调用的完整回答。']


def test_terminal_run_can_be_evicted_immediately_without_changing_emitted_status():
    pipe = Pipe()
    pipe.valves = Pipe.Valves(run_state_terminal_ttl_seconds=0)
    pipe._status('graph_snapshot', 'material-graph.sse.v2', graph_snapshot('terminal-now'), '')

    terminal = pipe._status(
        'terminal',
        'material-graph.sse.v2',
        {
            'action': 'material_graph',
            'event_type': 'terminal',
            'run_id': 'terminal-now',
            'outcome': 'completed',
            'done': True,
            'success': True,
        },
        '',
    )

    assert terminal is not None
    assert terminal['nodes'][0]['id'] == 'intake'
    assert terminal['done'] is True
    assert terminal['success'] is True
    assert 'terminal-now' not in pipe._runs
    assert 'terminal-now' not in pipe._run_access


def test_active_and_terminal_run_ttls_are_applied_independently():
    clock = ManualClock()
    pipe = Pipe()
    pipe._clock = clock
    pipe.valves = Pipe.Valves(
        run_state_max_entries=16,
        run_state_ttl_seconds=10,
        run_state_terminal_ttl_seconds=2,
    )
    pipe._status('graph_snapshot', None, graph_snapshot('active'), '')
    clock.set(1)
    pipe._status('graph_snapshot', None, graph_snapshot('terminal'), '')
    pipe._status(
        'terminal',
        None,
        {'run_id': 'terminal', 'outcome': 'completed', 'done': True, 'success': True},
        '',
    )

    clock.set(2.9)
    pipe._status('graph_snapshot', None, graph_snapshot('trigger-before-expiry'), '')
    assert {'active', 'terminal'} <= pipe._runs.keys()

    clock.set(3)
    pipe._status('graph_snapshot', None, graph_snapshot('trigger-terminal-expiry'), '')
    assert 'terminal' not in pipe._runs
    assert 'active' in pipe._runs

    clock.set(10)
    pipe._status('graph_snapshot', None, graph_snapshot('trigger-active-expiry'), '')
    assert 'active' not in pipe._runs
    assert set(pipe._runs) == set(pipe._run_access)


def test_run_cache_is_lru_bounded_and_prefers_evicting_terminal_states():
    clock = ManualClock()
    pipe = Pipe()
    pipe._clock = clock
    pipe.valves = Pipe.Valves(
        run_state_max_entries=2,
        run_state_ttl_seconds=100,
        run_state_terminal_ttl_seconds=100,
    )
    pipe._status('graph_snapshot', None, graph_snapshot('run-1'), '')
    clock.set(1)
    pipe._status('graph_snapshot', None, graph_snapshot('run-2'), '')
    clock.set(2)
    pipe._status(
        'node_state',
        None,
        {'run_id': 'run-1', 'node_id': 'intake', 'status': 'running'},
        '',
    )
    clock.set(3)
    pipe._status('graph_snapshot', None, graph_snapshot('run-3'), '')
    assert set(pipe._runs) == {'run-1', 'run-3'}

    clock.set(4)
    pipe._status(
        'terminal',
        None,
        {'run_id': 'run-1', 'outcome': 'completed', 'done': True, 'success': True},
        '',
    )
    clock.set(5)
    pipe._status('graph_snapshot', None, graph_snapshot('run-4'), '')
    assert set(pipe._runs) == {'run-3', 'run-4'}
    assert set(pipe._runs) == set(pipe._run_access)


def test_run_cache_remains_bounded_under_concurrent_status_updates():
    pipe = Pipe()
    pipe.valves = Pipe.Valves(
        run_state_max_entries=16,
        run_state_ttl_seconds=100,
        run_state_terminal_ttl_seconds=10,
    )

    def add_node(index):
        return pipe._status(
            'node_state',
            None,
            {
                'run_id': 'shared-run',
                'node_id': f'node-{index}',
                'status': 'running',
                'authoritative': False,
            },
            '',
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        statuses = list(executor.map(add_node, range(64)))
    assert all(status is not None for status in statuses)
    assert len(pipe._runs['shared-run']['nodes']) == 64

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(
            executor.map(
                lambda index: pipe._status(
                    'graph_snapshot',
                    None,
                    graph_snapshot(f'concurrent-{index}'),
                    '',
                ),
                range(64),
            )
        )
    assert len(pipe._runs) == 16
    assert set(pipe._runs) == set(pipe._run_access)
