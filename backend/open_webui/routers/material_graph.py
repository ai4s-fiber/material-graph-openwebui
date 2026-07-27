"""Authenticated BFF routes for Material Graph human-interrupt resumes."""

from __future__ import annotations

import os
import re
from collections.abc import AsyncIterator
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from open_webui.utils.auth import get_verified_user
from open_webui.utils.material_graph_auth import build_material_graph_auth_headers

router = APIRouter()
_RUN_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:-]{1,127}$')
_RESPONSE_HEADERS = {'content-type', 'cache-control', 'x-accel-buffering', 'x-request-id'}


def _api_base_url() -> str:
    value = os.getenv('MATERIAL_GRAPH_API_URL', 'http://material-graph-api:8000').rstrip('/')
    parsed = urlsplit(value)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
        raise RuntimeError('MATERIAL_GRAPH_API_URL is invalid')
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RuntimeError('MATERIAL_GRAPH_API_URL must not contain credentials or query data')
    return value


def _roles(user: object) -> list[str]:
    role = str(getattr(user, 'role', '') or '').strip()
    if not role:
        raise HTTPException(status_code=403, detail='Material Graph role is unavailable')
    return [role]


def _safe_run_id(run_id: str) -> str:
    if not _RUN_ID.fullmatch(run_id):
        raise HTTPException(status_code=422, detail='Invalid Material Graph run id')
    return run_id


async def _proxy(request: Request, user: object, upstream_path: str) -> Response:
    body = await request.body()
    signed_headers = build_material_graph_auth_headers(
        user_id=str(getattr(user, 'id', '')),
        roles=_roles(user),
        method=request.method,
        path=upstream_path,
    )
    headers = {
        **signed_headers,
        'Content-Type': request.headers.get('content-type', 'application/json'),
        'Accept': request.headers.get('accept', 'application/json'),
    }
    idempotency_key = request.headers.get('idempotency-key')
    if idempotency_key:
        headers['Idempotency-Key'] = idempotency_key[:256]

    client = httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=15.0))
    try:
        upstream_request = client.build_request(
            request.method,
            f'{_api_base_url()}{upstream_path}',
            content=body,
            headers=headers,
        )
        upstream = await client.send(upstream_request, stream=True)
    except (httpx.HTTPError, RuntimeError) as exc:
        await client.aclose()
        raise HTTPException(status_code=502, detail='Material Graph service is unavailable') from exc

    response_headers = {
        key: value for key, value in upstream.headers.items() if key.lower() in _RESPONSE_HEADERS
    }
    if upstream.headers.get('content-type', '').lower().startswith('text/event-stream'):

        async def stream() -> AsyncIterator[bytes]:
            try:
                async for chunk in upstream.aiter_raw():
                    yield chunk
            finally:
                await upstream.aclose()
                await client.aclose()

        response_headers['X-Accel-Buffering'] = 'no'
        return StreamingResponse(
            stream(),
            status_code=upstream.status_code,
            headers=response_headers,
            media_type='text/event-stream',
        )

    content = await upstream.aread()
    await upstream.aclose()
    await client.aclose()
    return Response(content=content, status_code=upstream.status_code, headers=response_headers)


@router.post('/runs/{run_id}/resume/stream')
async def resume_run_stream(
    run_id: str,
    request: Request,
    user=Depends(get_verified_user),
) -> Response:
    """Resume through Open WebUI so the browser never signs internal requests."""

    safe_run_id = _safe_run_id(run_id)
    return await _proxy(request, user, f'/runs/{safe_run_id}/resume/stream')


@router.post('/runs/{run_id}/resume')
async def resume_run(
    run_id: str,
    request: Request,
    user=Depends(get_verified_user),
) -> Response:
    safe_run_id = _safe_run_id(run_id)
    return await _proxy(request, user, f'/runs/{safe_run_id}/resume')
