"""Idempotently install the image-bundled Material Graph Pipe."""

from __future__ import annotations

import hashlib
import logging
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

FUNCTION_ID = 'material_graph'
FUNCTION_NAME = 'Material Graph Studio'
MANAGED_BY = 'ai4s-fiber/material-graph-openwebui'
SYSTEM_OWNER_ID = 'material-graph-bootstrap'
SOURCE_RELATIVE_PATH = 'integrations/material_graph_pipe.py'

_TRUE_VALUES = {'1', 'true', 'yes', 'on'}
_FALSE_VALUES = {'0', 'false', 'no', 'off'}


@dataclass(frozen=True)
class BootstrapResult:
    """Auditable outcome from a single startup reconciliation."""

    action: str
    function_id: str
    source_sha256: str
    image_revision: str


def _bootstrap_enabled() -> bool:
    raw = os.getenv('MATERIAL_GRAPH_PIPE_BOOTSTRAP_ENABLED', 'true').strip().lower()
    if raw in _TRUE_VALUES:
        return True
    if raw in _FALSE_VALUES:
        return False
    raise RuntimeError('MATERIAL_GRAPH_PIPE_BOOTSTRAP_ENABLED must be one of true/false, yes/no, on/off, or 1/0')


def _default_source_path() -> Path:
    # This module lives at /app/backend/open_webui/utils in the runtime image.
    backend_root = Path(__file__).resolve().parents[2]
    return backend_root / SOURCE_RELATIVE_PATH


def _source_path() -> Path:
    override = os.getenv('MATERIAL_GRAPH_PIPE_SOURCE_PATH', '').strip()
    return Path(override) if override else _default_source_path()


def _image_revision() -> str:
    return os.getenv('WEBUI_BUILD_VERSION', '').strip() or os.getenv('WEBUI_BUILD_HASH', '').strip() or 'dev-build'


def _meta(*, source_sha256: str, image_revision: str) -> dict[str, Any]:
    return {
        'description': 'Managed Material Graph Studio execution pipe.',
        'manifest': {
            'title': FUNCTION_NAME,
            'version': source_sha256[:12],
            'managed_by': MANAGED_BY,
            'managed_function_id': FUNCTION_ID,
            'source_path': SOURCE_RELATIVE_PATH,
            'source_sha256': source_sha256,
            'image_revision': image_revision,
        },
    }


def _meta_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    model_dump = getattr(value, 'model_dump', None)
    if callable(model_dump):
        return model_dump()
    return {}


def _managed_by_us(row: Any) -> bool:
    manifest = _meta_dict(getattr(row, 'meta', None)).get('manifest') or {}
    return isinstance(manifest, dict) and manifest.get('managed_by') == MANAGED_BY


def _content_sha256(content: str) -> str:
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def _migrate_legacy_scenario_valve(value: Any) -> Any:
    """Migrate only the retired default while preserving operator valves."""

    valves = value
    if isinstance(value, str):
        from open_webui.utils.valves import decrypt_valves, encrypt_valves

        decrypted = decrypt_valves(value)
        if decrypted.get('scenario') != 'generic_material':
            return value
        valves = decrypted
        migrated = {**valves, 'scenario': 'custom'}
        return encrypt_valves(migrated)
    if not isinstance(valves, dict) or valves.get('scenario') != 'generic_material':
        return value
    return {**valves, 'scenario': 'custom'}


async def _default_validator(validation_id: str, content: str) -> str:
    from open_webui.utils.plugin import load_function_module_by_id

    _, function_type, _ = await load_function_module_by_id(
        validation_id,
        content=content,
    )
    return function_type


async def _default_owner_resolver(db: Any) -> str:
    from open_webui.models.users import User
    from sqlalchemy import select

    result = await db.execute(select(User).where(User.role == 'admin').order_by(User.created_at).limit(1))
    owner = result.scalars().first()
    return owner.id if owner is not None else SYSTEM_OWNER_ID


async def _reconcile_once(
    *,
    content: str,
    source_sha256: str,
    image_revision: str,
    db: Any,
    owner_resolver: Callable[[Any], Awaitable[str]],
    function_factory: Callable[..., Any],
) -> BootstrapResult:
    row = await db.get(function_factory, FUNCTION_ID, with_for_update=True)
    owner_id = await owner_resolver(db)
    desired_meta = _meta(
        source_sha256=source_sha256,
        image_revision=image_revision,
    )
    now = int(time.time())

    if row is None:
        row = function_factory(
            id=FUNCTION_ID,
            user_id=owner_id,
            name=FUNCTION_NAME,
            type='pipe',
            content=content,
            meta=desired_meta,
            valves=None,
            is_active=True,
            is_global=False,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        await db.flush()
        await db.commit()
        return BootstrapResult(
            action='created',
            function_id=FUNCTION_ID,
            source_sha256=source_sha256,
            image_revision=image_revision,
        )

    existing_content = getattr(row, 'content', '') or ''
    content_matches = _content_sha256(existing_content) == source_sha256
    managed = _managed_by_us(row)
    if not managed and not content_matches:
        raise RuntimeError(
            f'function id {FUNCTION_ID!r} already exists but is not managed by {MANAGED_BY}; refusing to overwrite it'
        )

    desired_owner = getattr(row, 'user_id', None) or owner_id
    if desired_owner == SYSTEM_OWNER_ID and owner_id != SYSTEM_OWNER_ID:
        desired_owner = owner_id
    desired_valves = _migrate_legacy_scenario_valve(getattr(row, 'valves', None))

    desired = {
        'user_id': desired_owner,
        'name': FUNCTION_NAME,
        'type': 'pipe',
        'content': content,
        'meta': desired_meta,
        'valves': desired_valves,
        'is_active': True,
        'is_global': False,
    }
    changed = any(getattr(row, key, None) != value for key, value in desired.items())
    if changed:
        for key, value in desired.items():
            setattr(row, key, value)
        row.updated_at = now
        await db.flush()
        await db.commit()
        action = 'updated' if managed else 'adopted'
    else:
        action = 'unchanged'

    return BootstrapResult(
        action=action,
        function_id=FUNCTION_ID,
        source_sha256=source_sha256,
        image_revision=image_revision,
    )


async def ensure_material_graph_pipe(
    *,
    source_path: Path | None = None,
    validator: Callable[[str, str], Awaitable[str]] | None = None,
    db_factory: Callable[[], Any] | None = None,
    owner_resolver: Callable[[Any], Awaitable[str]] | None = None,
    function_factory: Callable[..., Any] | None = None,
) -> BootstrapResult | None:
    """Reconcile the bundled pipe into Open WebUI's function table.

    The fixed primary key and row lock make repeated starts idempotent. A
    primary-key race between replicas is retried once. Existing operator valves
    are never touched. An unrelated function using the managed ID is a hard
    startup error rather than an implicit overwrite.
    """

    if not _bootstrap_enabled():
        log.info('Material Graph Pipe bootstrap is disabled')
        return None

    path = source_path or _source_path()
    try:
        content = path.read_text(encoding='utf-8')
    except OSError as exc:
        raise RuntimeError(f'bundled Material Graph Pipe source is unavailable at {path}') from exc

    source_sha256 = _content_sha256(content)
    revision = _image_revision()
    validate = validator or _default_validator
    validation_id = f'{FUNCTION_ID}_bootstrap_{source_sha256[:12]}'
    function_type = await validate(validation_id, content)
    if function_type != 'pipe':
        raise RuntimeError(f'bundled Material Graph function must be a pipe, got {function_type!r}')

    if db_factory is None:
        from open_webui.internal.db import get_async_db_context

        db_factory = get_async_db_context
    if owner_resolver is None:
        owner_resolver = _default_owner_resolver
    if function_factory is None:
        from open_webui.models.functions import Function

        function_factory = Function

    from sqlalchemy.exc import IntegrityError

    for attempt in range(2):
        async with db_factory() as db:
            try:
                result = await _reconcile_once(
                    content=content,
                    source_sha256=source_sha256,
                    image_revision=revision,
                    db=db,
                    owner_resolver=owner_resolver,
                    function_factory=function_factory,
                )
                log.info(
                    'Material Graph Pipe bootstrap %s: id=%s source_sha256=%s image_revision=%s',
                    result.action,
                    result.function_id,
                    result.source_sha256,
                    result.image_revision,
                )
                return result
            except IntegrityError:
                await db.rollback()
                if attempt == 0:
                    continue
                raise

    raise RuntimeError('Material Graph Pipe bootstrap did not converge')
