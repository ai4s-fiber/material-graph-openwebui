from __future__ import annotations

import asyncio
import hashlib
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))

from open_webui.utils.material_graph_pipe_bootstrap import (  # noqa: E402
    FUNCTION_ID,
    MANAGED_BY,
    ensure_material_graph_pipe,
)


class FakeFunction:
    def __init__(self, **values):
        for key, value in values.items():
            setattr(self, key, value)


class FakeSession:
    def __init__(self, row=None):
        self.row = row
        self.commits = 0
        self.flushes = 0
        self.rollbacks = 0

    async def get(self, model, row_id, *, with_for_update=False):
        assert model is FakeFunction
        assert row_id == FUNCTION_ID
        assert with_for_update is True
        return self.row

    def add(self, row):
        assert self.row is None
        self.row = row

    async def flush(self):
        self.flushes += 1

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def db_factory(session):
    @asynccontextmanager
    async def context():
        yield session

    return context


async def validate_pipe(validation_id, content):
    assert validation_id.startswith(f'{FUNCTION_ID}_bootstrap_')
    assert content
    return 'pipe'


async def resolve_admin(_db):
    return 'admin-1'


def run_bootstrap(source_path, session):
    return asyncio.run(
        ensure_material_graph_pipe(
            source_path=source_path,
            validator=validate_pipe,
            db_factory=db_factory(session),
            owner_resolver=resolve_admin,
            function_factory=FakeFunction,
        )
    )


def test_bootstrap_creates_active_auditable_pipe_and_is_idempotent(tmp_path, monkeypatch):
    source = 'class Pipe:\\n    pass\\n'
    source_path = tmp_path / 'material_graph_pipe.py'
    source_path.write_text(source, encoding='utf-8')
    monkeypatch.setenv('WEBUI_BUILD_VERSION', 'sha-test-revision')
    session = FakeSession()

    first = run_bootstrap(source_path, session)
    second = run_bootstrap(source_path, session)

    digest = hashlib.sha256(source.encode()).hexdigest()
    assert first.action == 'created'
    assert second.action == 'unchanged'
    assert session.commits == 1
    assert session.flushes == 1
    assert session.row.id == FUNCTION_ID
    assert session.row.user_id == 'admin-1'
    assert session.row.type == 'pipe'
    assert session.row.is_active is True
    assert session.row.is_global is False
    assert session.row.valves is None
    assert session.row.meta['manifest'] == {
        'title': 'Material Graph Studio',
        'version': digest[:12],
        'managed_by': MANAGED_BY,
        'managed_function_id': FUNCTION_ID,
        'source_path': 'integrations/material_graph_pipe.py',
        'source_sha256': digest,
        'image_revision': 'sha-test-revision',
    }


def test_bootstrap_updates_only_managed_row_and_preserves_valves(tmp_path):
    old_source = 'class Pipe:\\n    old = True\\n'
    new_source = 'class Pipe:\\n    new = True\\n'
    source_path = tmp_path / 'material_graph_pipe.py'
    source_path.write_text(new_source, encoding='utf-8')
    valves = {'material_graph_api_url': 'http://material-graph-api:8000'}
    row = FakeFunction(
        id=FUNCTION_ID,
        user_id='admin-1',
        name='Old name',
        type='pipe',
        content=old_source,
        meta={'manifest': {'managed_by': MANAGED_BY}},
        valves=valves,
        is_active=False,
        is_global=True,
        updated_at=1,
        created_at=1,
    )
    session = FakeSession(row)

    result = run_bootstrap(source_path, session)

    assert result.action == 'updated'
    assert row.content == new_source
    assert row.is_active is True
    assert row.is_global is False
    assert row.valves is valves
    assert session.commits == 1


def test_bootstrap_migrates_only_the_legacy_generic_scenario_valve(tmp_path):
    old_source = 'class Pipe:\\n    old = True\\n'
    new_source = 'class Pipe:\\n    new = True\\n'
    source_path = tmp_path / 'material_graph_pipe.py'
    source_path.write_text(new_source, encoding='utf-8')
    valves = {
        'material_graph_api_url': 'http://operator-api:9000',
        'scenario': 'generic_material',
        'timeout_seconds': 420,
    }
    row = FakeFunction(
        id=FUNCTION_ID,
        user_id='admin-1',
        name='Material Graph Studio',
        type='pipe',
        content=old_source,
        meta={'manifest': {'managed_by': MANAGED_BY}},
        valves=valves,
        is_active=True,
        is_global=False,
        updated_at=1,
        created_at=1,
    )
    session = FakeSession(row)

    result = run_bootstrap(source_path, session)

    assert result.action == 'updated'
    assert row.valves == {
        'material_graph_api_url': 'http://operator-api:9000',
        'scenario': 'custom',
        'timeout_seconds': 420,
    }
    assert valves['scenario'] == 'generic_material'


def test_bootstrap_preserves_explicit_demo_scenario(tmp_path):
    source = 'class Pipe:\\n    pass\\n'
    source_path = tmp_path / 'material_graph_pipe.py'
    source_path.write_text(source, encoding='utf-8')
    valves = {'scenario': 'polyimide_design'}
    row = FakeFunction(
        id=FUNCTION_ID,
        user_id='admin-1',
        name='Material Graph Studio',
        type='pipe',
        content=source,
        meta={'manifest': {'managed_by': MANAGED_BY}},
        valves=valves,
        is_active=True,
        is_global=False,
        updated_at=1,
        created_at=1,
    )
    session = FakeSession(row)

    result = run_bootstrap(source_path, session)

    assert result.action == 'updated'
    assert row.valves is valves


def test_bootstrap_adopts_identical_manual_import_without_overwriting_valves(tmp_path):
    source = 'class Pipe:\\n    pass\\n'
    source_path = tmp_path / 'material_graph_pipe.py'
    source_path.write_text(source, encoding='utf-8')
    valves = {'timeout_seconds': 300}
    row = FakeFunction(
        id=FUNCTION_ID,
        user_id='admin-1',
        name='Manual import',
        type='pipe',
        content=source,
        meta={'description': 'manual'},
        valves=valves,
        is_active=False,
        is_global=False,
        updated_at=1,
        created_at=1,
    )
    session = FakeSession(row)

    result = run_bootstrap(source_path, session)

    assert result.action == 'adopted'
    assert row.meta['manifest']['managed_by'] == MANAGED_BY
    assert row.valves is valves


def test_bootstrap_rejects_unmanaged_id_collision(tmp_path):
    source_path = tmp_path / 'material_graph_pipe.py'
    source_path.write_text('class Pipe:\\n    pass\\n', encoding='utf-8')
    row = FakeFunction(
        id=FUNCTION_ID,
        user_id='operator',
        content='class Pipe:\\n    unrelated = True\\n',
        meta={},
    )

    with pytest.raises(RuntimeError, match='refusing to overwrite'):
        run_bootstrap(source_path, FakeSession(row))


def test_bootstrap_can_be_explicitly_disabled_without_reading_source(tmp_path, monkeypatch):
    monkeypatch.setenv('MATERIAL_GRAPH_PIPE_BOOTSTRAP_ENABLED', 'false')

    result = asyncio.run(ensure_material_graph_pipe(source_path=tmp_path / 'missing.py'))

    assert result is None


def test_release_image_and_startup_hook_own_the_pipe_lifecycle():
    dockerfile = (ROOT / 'Dockerfile').read_text(encoding='utf-8')
    main = (ROOT / 'backend' / 'open_webui' / 'main.py').read_text(encoding='utf-8')
    bootstrap = (ROOT / 'backend' / 'open_webui' / 'utils' / 'material_graph_pipe_bootstrap.py').read_text(
        encoding='utf-8'
    )

    assert (
        'COPY --chown=$UID:$GID integrations/material_graph_pipe.py /app/backend/integrations/material_graph_pipe.py'
    ) in dockerfile
    assert 'MATERIAL_GRAPH_PIPE_BOOTSTRAP_ENABLED=true' in dockerfile
    assert 'await ensure_material_graph_pipe()' in main
    assert main.index('await ensure_material_graph_pipe()') < main.index(
        'await install_tool_and_function_dependencies()'
    )
    assert 'Config.upsert' not in bootstrap
    assert 'ENABLE_SIGNUP' not in bootstrap
