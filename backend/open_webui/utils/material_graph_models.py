from __future__ import annotations

import os
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

MATERIAL_GRAPH_STUDIO_MODE_ENV = 'MATERIAL_GRAPH_STUDIO_MODE'
MATERIAL_GRAPH_STUDIO_MODEL_ID_ENV = 'MATERIAL_GRAPH_STUDIO_MODEL_ID'
DEFAULT_MATERIAL_GRAPH_MODEL_ID = 'material_graph'


class MaterialGraphStudioModelError(RuntimeError):
    pass


def material_graph_studio_mode_enabled(
    environment: Mapping[str, str] | None = None,
) -> bool:
    value = (environment or os.environ).get(MATERIAL_GRAPH_STUDIO_MODE_ENV, 'false')
    normalized = value.strip().lower()
    if normalized in {'1', 'true', 'yes', 'on'}:
        return True
    if normalized in {'0', 'false', 'no', 'off', ''}:
        return False
    raise MaterialGraphStudioModelError(f'{MATERIAL_GRAPH_STUDIO_MODE_ENV} must be a boolean value')


def material_graph_studio_model_id(
    environment: Mapping[str, str] | None = None,
) -> str:
    value = (environment or os.environ).get(
        MATERIAL_GRAPH_STUDIO_MODEL_ID_ENV,
        DEFAULT_MATERIAL_GRAPH_MODEL_ID,
    )
    model_id = value.strip()
    if not model_id or any(character.isspace() for character in model_id):
        raise MaterialGraphStudioModelError(f'{MATERIAL_GRAPH_STUDIO_MODEL_ID_ENV} must be a non-empty model id')
    return model_id


async def get_material_graph_studio_models(
    *,
    function_loader: Callable[..., Awaitable[Sequence[Any]]] | None = None,
    environment: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    if function_loader is None:
        from open_webui.models.functions import Functions

        function_loader = Functions.get_functions_by_type
    loader = function_loader
    model_id = material_graph_studio_model_id(environment)
    pipes = await loader('pipe', active_only=True)
    matches = [pipe for pipe in pipes if pipe.id == model_id and pipe.type == 'pipe']
    if len(matches) != 1:
        raise MaterialGraphStudioModelError(f'expected one active local pipe named {model_id!r}, found {len(matches)}')

    pipe = matches[0]
    return [
        {
            'id': pipe.id,
            'name': pipe.name,
            'object': 'model',
            'created': pipe.created_at,
            'owned_by': 'openai',
            'pipe': {'type': 'pipe'},
            'has_user_valves': False,
            'actions': [],
            'filters': [],
        }
    ]
