from __future__ import annotations

import asyncio
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

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


async def forward(pipe, event, client=None, *, resync_base_url=None, auth_headers=None):
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
                {'messages': [{'role': 'user', 'content': 'design'}]},
                __event_emitter__=emitter,
                __user__={'id': 'user-12345678', 'role': 'user'},
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
    }
    assert emitted[0]['data']['endpoint'] == '/api/v1/material-graph'
    load_material_graph_hmac_secret.cache_clear()


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
