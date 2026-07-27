"""Server-side signer for the Material Graph internal API boundary."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

AUTH_HEADER = 'X-Material-Graph-User-Context'
TOKEN_VERSION = 'v1'
_MIN_SECRET_BYTES = 32
_MAX_SECRET_BYTES = 4096


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode('ascii')


def _canonical(payload: dict[str, object]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(',', ':'),
        sort_keys=True,
    ).encode('utf-8')


@lru_cache(maxsize=1)
def load_material_graph_hmac_secret() -> bytes:
    if os.getenv('MATERIAL_GRAPH_HMAC_SECRET'):
        raise RuntimeError('MATERIAL_GRAPH_HMAC_SECRET must be supplied through a secret file')
    configured = os.getenv('MATERIAL_GRAPH_HMAC_SECRET_FILE', '').strip()
    if not configured:
        raise RuntimeError('missing MATERIAL_GRAPH_HMAC_SECRET_FILE')
    path = Path(configured)
    if not path.is_file() or path.stat().st_size > _MAX_SECRET_BYTES:
        raise RuntimeError('Material Graph HMAC secret file is unavailable or oversized')
    secret = path.read_bytes().strip()
    if not _MIN_SECRET_BYTES <= len(secret) <= _MAX_SECRET_BYTES:
        raise RuntimeError('Material Graph HMAC secret must contain 32 to 4096 bytes')
    return secret


def _ttl_seconds() -> int:
    try:
        value = int(os.getenv('MATERIAL_GRAPH_HMAC_TTL_SECONDS', '30'))
    except ValueError as exc:
        raise RuntimeError('MATERIAL_GRAPH_HMAC_TTL_SECONDS must be an integer') from exc
    if not 5 <= value <= 60:
        raise RuntimeError('MATERIAL_GRAPH_HMAC_TTL_SECONDS must be between 5 and 60')
    return value


def _roles(values: Iterable[str]) -> list[str]:
    if isinstance(values, str | bytes):
        raise RuntimeError('Material Graph roles must be a list')
    roles = sorted({str(value).strip() for value in values if str(value).strip()})
    if not 1 <= len(roles) <= 16 or any(len(role) > 64 for role in roles):
        raise RuntimeError('Material Graph roles are invalid')
    return roles


def build_material_graph_auth_headers(
    *,
    user_id: str,
    roles: Iterable[str],
    method: str,
    path: str,
    request_id: str | None = None,
    now: int | None = None,
    secret: bytes | None = None,
) -> dict[str, str]:
    """Sign a one-request context; callers must never return it to a browser."""

    normalized_user = str(user_id).strip()
    if not normalized_user or len(normalized_user) > 128:
        raise RuntimeError('Material Graph user_id is invalid')
    if not path.startswith('/') or len(path) > 2048:
        raise RuntimeError('Material Graph path is invalid')
    correlation_id = request_id or f'owui-{uuid.uuid4()}'
    current = int(time.time()) if now is None else int(now)
    payload: dict[str, object] = {
        'user_id': normalized_user,
        'roles': _roles(roles),
        'request_id': correlation_id,
        'exp': current + _ttl_seconds(),
        'method': method.upper(),
        'path': path,
    }
    payload_segment = _b64url(_canonical(payload))
    signing_input = f'{TOKEN_VERSION}.{payload_segment}'.encode('ascii')
    signing_secret = secret if secret is not None else load_material_graph_hmac_secret()
    if not _MIN_SECRET_BYTES <= len(signing_secret) <= _MAX_SECRET_BYTES:
        raise RuntimeError('Material Graph HMAC secret is invalid')
    signature = hmac.new(signing_secret, signing_input, hashlib.sha256).digest()
    return {
        AUTH_HEADER: f'{TOKEN_VERSION}.{payload_segment}.{_b64url(signature)}',
        'X-Request-ID': correlation_id,
    }
