from __future__ import annotations
import asyncio
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'integrations'))
from material_graph_pipe import Pipe  # noqa: E402


async def forward(pipe, event):
    emitted = []

    async def emitter(item):
        emitted.append(item)

    return [x async for x in pipe._forward_event(event, 'https://material.example/api', emitter)], emitted


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


def test_v2_assistant_delta_and_final_message_are_not_duplicated():
    pipe = Pipe()
    delta = dict(
        contract_version='material-graph.sse.v2',
        type='assistant_delta',
        event_type='assistant_delta',
        run_id='r-v2',
        content_mode='incremental',
        source='provider',
        delta='真实增量',
        token='真实增量',
    )
    final = dict(
        contract_version='material-graph.sse.v2',
        type='assistant_message',
        event_type='assistant_message',
        run_id='r-v2',
        content_mode='final',
        content='真实增量',
        delta='真实增量',
    )
    assert asyncio.run(forward(pipe, delta))[0] == ['真实增量']
    assert asyncio.run(forward(pipe, final))[0] == []


def test_v2_assistant_message_without_delta_is_forwarded_once():
    final = dict(
        contract_version='material-graph.sse.v2',
        type='assistant_message',
        event_type='assistant_message',
        run_id='r-v2-final',
        content_mode='final',
        content='完整总结',
        delta='完整总结',
    )
    assert asyncio.run(forward(Pipe(), final))[0] == ['完整总结']


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
