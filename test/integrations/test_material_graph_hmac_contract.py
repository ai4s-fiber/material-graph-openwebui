from __future__ import annotations

import asyncio
import importlib.util
import json
import re
import sys
from hashlib import sha256
from pathlib import Path
from types import ModuleType, SimpleNamespace

import httpx
from fastapi import Request

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / 'backend'
CONTRACT = ROOT / 'contracts' / 'openwebui' / 'hmac-v1.json'
SOURCE_LOCK = ROOT / 'contracts' / 'openwebui' / 'hmac-v1.source.json'
CI_WORKFLOW = ROOT / '.github' / 'workflows' / 'material-graph-ci.yml'
IMAGE_WORKFLOW = ROOT / '.github' / 'workflows' / 'material-graph-image.yml'
sys.path.insert(0, str(BACKEND))

from open_webui.utils.material_graph_auth import (  # noqa: E402
    AUTH_HEADER,
    TOKEN_VERSION,
    build_material_graph_auth_headers,
)


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding='utf-8'))


def _canonical_sha256(payload: object) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(',', ':'),
        sort_keys=True,
    ).encode('utf-8')
    return sha256(canonical).hexdigest()


def _load_router(monkeypatch):
    auth_stub = ModuleType('open_webui.utils.auth')
    auth_stub.get_verified_user = lambda: None
    monkeypatch.setitem(sys.modules, 'open_webui.utils.auth', auth_stub)
    module_path = BACKEND / 'open_webui' / 'routers' / 'material_graph.py'
    spec = importlib.util.spec_from_file_location('material_graph_router_under_test', module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _request(*, path: str, headers: list[tuple[bytes, bytes]], body: bytes) -> Request:
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {'type': 'http.disconnect'}
        sent = True
        return {'type': 'http.request', 'body': body, 'more_body': False}

    return Request(
        {
            'type': 'http',
            'http_version': '1.1',
            'method': 'POST',
            'scheme': 'https',
            'path': path,
            'raw_path': path.encode('ascii'),
            'query_string': b'',
            'headers': headers,
            'client': ('127.0.0.1', 12345),
            'server': ('testserver', 443),
        },
        receive,
    )


def test_fork_snapshot_matches_the_locked_neutral_contract() -> None:
    contract = _load_json(CONTRACT)
    source = _load_json(SOURCE_LOCK)

    assert {
        name: source[name]
        for name in (
            'schema_version',
            'contract_id',
            'contract_version',
            'snapshot_path',
            'canonical_sha256',
            'source_repository',
            'source_path',
        )
    } == {
        'schema_version': 1,
        'contract_id': 'material-graph-openwebui-hmac',
        'contract_version': 'hmac-v1',
        'snapshot_path': 'contracts/openwebui/hmac-v1.json',
        'canonical_sha256': '18ec590ef0486b174acbd5af5e1f165fdb6430b7c46eef78263f3c5f1bdf67dc',
        'source_repository': 'https://github.com/ai4s-fiber/material-graph-studio',
        'source_path': 'contracts/openwebui/hmac-v1.json',
    }
    source_commit = source['source_commit']
    if source_commit == 'PENDING_MASTER_SQUASH':
        assert source['publishable'] is False
        assert source['blocked_reason'] == (
            'The source commit must be replaced with the exact material-graph-studio master '
            'squash commit before this Fork may publish an image.'
        )
    else:
        assert re.fullmatch(r'[0-9a-f]{40}', source_commit)
        assert source['publishable'] is True
        assert 'blocked_reason' not in source
    assert _canonical_sha256(contract) == source['canonical_sha256']
    assert contract['schema_version'] == source['schema_version']
    assert contract['contract_id'] == source['contract_id']
    assert contract['contract_version'] == source['contract_version']


def test_openwebui_signer_exactly_emits_the_hmac_v1_gold_vector(monkeypatch) -> None:
    contract = _load_json(CONTRACT)
    assert contract['headers']['user_context'] == AUTH_HEADER
    assert contract['token']['version'] == TOKEN_VERSION
    monkeypatch.setenv('MATERIAL_GRAPH_HMAC_TTL_SECONDS', '30')

    for vector in contract['vectors']:
        claims = vector['claims']
        headers = build_material_graph_auth_headers(
            user_id=claims['user_id'],
            roles=claims['roles'],
            method=vector['request']['method'],
            path=vector['request']['path'],
            request_id=claims['request_id'],
            now=vector['now'],
            secret=vector['secret_utf8'].encode('utf-8'),
        )
        assert headers == {
            contract['headers']['user_context']: vector['token_value'],
            contract['headers']['request_id']: claims['request_id'],
        }


def test_bff_signs_authoritative_method_path_user_and_roles_without_forwarding_spoofed_headers(
    monkeypatch,
) -> None:
    router = _load_router(monkeypatch)
    signed = {
        AUTH_HEADER: 'signed-by-openwebui',
        'X-Request-ID': 'owui-authoritative-request',
    }
    signer_call: dict[str, object] = {}
    upstream: dict[str, object] = {}
    body = b'{"approved":true}'

    def fake_signer(**kwargs):
        signer_call.update(kwargs)
        return signed

    def handler(request: httpx.Request) -> httpx.Response:
        upstream['method'] = request.method
        upstream['url'] = str(request.url)
        upstream['headers'] = dict(request.headers)
        upstream['body'] = request.content
        return httpx.Response(200, json={'accepted': True})

    request = _request(
        path='/api/v1/material-graph/runs/run-123/resume/stream',
        headers=[
            (b'content-type', b'application/json'),
            (b'accept', b'text/event-stream'),
            (b'idempotency-key', b'resume-key'),
            (b'x-material-graph-user-context', b'forged-browser-context'),
            (b'x-request-id', b'forged-browser-request'),
            (b'authorization', b'Bearer forged-browser-token'),
        ],
        body=body,
    )
    user = SimpleNamespace(id='researcher-42', role='researcher')

    async def exercise():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        monkeypatch.setattr(router, 'build_material_graph_auth_headers', fake_signer)
        monkeypatch.setattr(router.httpx, 'AsyncClient', lambda **_kwargs: client)
        response = await router._proxy(request, user, '/runs/run-123/resume/stream')
        return response

    response = asyncio.run(exercise())

    assert response.status_code == 200
    assert signer_call == {
        'user_id': 'researcher-42',
        'roles': ['researcher'],
        'method': 'POST',
        'path': '/runs/run-123/resume/stream',
    }
    assert upstream['method'] == 'POST'
    assert upstream['url'] == 'http://material-graph-api:8000/runs/run-123/resume/stream'
    assert upstream['body'] == body
    assert upstream['headers']['x-material-graph-user-context'] == 'signed-by-openwebui'
    assert upstream['headers']['x-request-id'] == 'owui-authoritative-request'
    assert upstream['headers']['idempotency-key'] == 'resume-key'
    assert 'authorization' not in upstream['headers']
    assert all('forged-browser' not in value for value in upstream['headers'].values())


def test_resume_routes_derive_only_the_validated_upstream_paths(monkeypatch) -> None:
    router = _load_router(monkeypatch)
    calls: list[tuple[object, object, str]] = []
    request = _request(path='/ignored', headers=[], body=b'{}')
    user = SimpleNamespace(id='user-1', role='user')

    async def fake_proxy(received_request, received_user, upstream_path):
        calls.append((received_request, received_user, upstream_path))
        return httpx.Response(204)

    monkeypatch.setattr(router, '_proxy', fake_proxy)
    asyncio.run(router.resume_run_stream('run-123', request, user))
    asyncio.run(router.resume_run('run-123', request, user))

    assert calls == [
        (request, user, '/runs/run-123/resume/stream'),
        (request, user, '/runs/run-123/resume'),
    ]


def test_ci_is_offline_and_image_publication_fails_closed_while_the_source_is_pending() -> None:
    ci = CI_WORKFLOW.read_text(encoding='utf-8')
    image = IMAGE_WORKFLOW.read_text(encoding='utf-8')

    assert 'test/integrations/test_material_graph_hmac_contract.py' in ci
    assert (
        'curl '
        not in ci.split('Run Material Graph integration and release contract tests', maxsplit=1)[1].split(
            '- name: Set up Node.js',
            maxsplit=1,
        )[0]
    )
    assert 'Require a publishable Material Graph HMAC contract lock' in image
    assert 'PENDING_MASTER_SQUASH' in image
    assert 'publishable' in image
