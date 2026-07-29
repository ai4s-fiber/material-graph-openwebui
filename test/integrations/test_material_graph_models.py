from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))

from open_webui.utils.material_graph_models import (  # noqa: E402
    MaterialGraphStudioModelError,
    get_material_graph_studio_models,
    material_graph_studio_mode_enabled,
)


async def _local_pipe_loader(function_type, *, active_only):
    assert function_type == 'pipe'
    assert active_only is True
    return [
        SimpleNamespace(
            id='material_graph',
            name='Material Graph Studio',
            type='pipe',
            created_at=123,
        )
    ]


def test_studio_model_discovery_is_local_bounded_and_returns_one_fixed_pipe():
    models = asyncio.run(
        asyncio.wait_for(
            get_material_graph_studio_models(
                function_loader=_local_pipe_loader,
                environment={'MATERIAL_GRAPH_STUDIO_MODEL_ID': 'material_graph'},
            ),
            timeout=0.1,
        )
    )

    assert models == [
        {
            'id': 'material_graph',
            'name': 'Material Graph Studio',
            'object': 'model',
            'created': 123,
            'owned_by': 'openai',
            'pipe': {'type': 'pipe'},
            'has_user_valves': False,
            'actions': [],
            'filters': [],
        }
    ]


def test_studio_model_discovery_fails_fast_when_the_managed_pipe_is_missing():
    async def no_pipes(*_args, **_kwargs):
        return []

    with pytest.raises(MaterialGraphStudioModelError, match='expected one active local pipe'):
        asyncio.run(
            asyncio.wait_for(
                get_material_graph_studio_models(
                    function_loader=no_pipes,
                    environment={'MATERIAL_GRAPH_STUDIO_MODEL_ID': 'material_graph'},
                ),
                timeout=0.1,
            )
        )


def test_studio_mode_parser_rejects_ambiguous_values():
    assert material_graph_studio_mode_enabled({'MATERIAL_GRAPH_STUDIO_MODE': 'true'})
    assert not material_graph_studio_mode_enabled({'MATERIAL_GRAPH_STUDIO_MODE': 'false'})
    with pytest.raises(MaterialGraphStudioModelError, match='must be a boolean'):
        material_graph_studio_mode_enabled({'MATERIAL_GRAPH_STUDIO_MODE': 'sometimes'})


def test_release_defaults_disable_external_model_discovery():
    dockerfile = (ROOT / 'Dockerfile').read_text(encoding='utf-8')
    model_utils = (ROOT / 'backend' / 'open_webui' / 'utils' / 'models.py').read_text(encoding='utf-8')

    assert 'MATERIAL_GRAPH_STUDIO_MODE=true' in dockerfile
    assert 'MATERIAL_GRAPH_STUDIO_MODEL_ID=material_graph' in dockerfile
    assert 'DEFAULT_MODELS=material_graph' in dockerfile
    assert 'ENABLE_OLLAMA_API=false' in dockerfile
    assert 'ENABLE_OPENAI_API=false' in dockerfile
    fast_path = model_utils.index('if material_graph_studio_mode_enabled():')
    provider_discovery = model_utils.index("config = await Config.get_many(\n        'models.base_models_cache'")
    assert fast_path < provider_discovery
    assert 'return models' in model_utils[fast_path:provider_discovery]
