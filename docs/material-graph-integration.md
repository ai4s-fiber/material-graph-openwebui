# Material Graph Studio Open WebUI patch

## Upstream

- Repository: `open-webui/open-webui`
- Tag: `v0.10.2`
- Commit: `ecd48e2f718220a6400ecf49eafd4867a38feb10`
- License and history: upstream `LICENSE`, `LICENSE_NOTICE`, and `LICENSE_HISTORY` remain byte-for-byte present in this directory.
- Added dependency: `@dagrejs/dagre@^1.1.5` (MIT). The existing `@xyflow/svelte@^0.1.19` package is reused.

## Contract

The Pipe accepts legacy Open WebUI status envelopes plus `material-graph.sse.v2` graph snapshots, versioned graph deltas, explicit provider text deltas, final assistant messages, logs, `assistant_form`, and terminal-outcome events. It reconstructs one canonical `action=material_graph` status, preserves `graph_version`, and never maps a failed, blocked, budget-stopped, rejected, or cancelled run to success. A `base_version` gap triggers an authoritative `GET /runs/{run_id}/graph` resync instead of applying an unsafe patch.

Workflow topology is authoritative when supplied by `WorkflowDefinition`. Partial node/log events update runtime state while retaining every node and edge. `current_node` moves only on an authoritative node event or an explicit backend field.

## Checkpoint resume

Forms prefer `POST /runs/{run_id}/resume/stream`. A 404, 405, or 501 safely falls back to the form's legacy `/resume` path. Both calls carry the same `run_id`, `checkpoint_id`, values, and deterministic `Idempotency-Key`. Any response containing a different run id is rejected. Explicit provider deltas append to the assistant message; a locally synthesized summary arrives once as `assistant_message` with `content_mode=final`, never as fabricated token chunks. Material Graph status history is compacted at 128 entries, and Dagre layout is recalculated only when node or edge topology changes.

The browser sends those requests only to the authenticated same-origin Open WebUI BFF at `/api/v1/material-graph`. The BFF and Pipe sign a new 30-second HMAC context containing `user_id`, `roles`, `request_id`, `exp`, method, and upstream path. Material Graph consumes each request ID once. Nginx has no Graph API upstream, and strips any client-supplied internal authentication header before forwarding to Open WebUI.

## JSON Schema forms

Object properties cover required values, numeric minimum/maximum, scalar enums, array enums as multi-select, booleans, descriptions, defaults, typed number serialization, and field-level validation errors. Accepted forms become resolved and cannot be submitted twice from the same rendered component.

## Patch surface

- `integrations/material_graph_pipe.py`: transport and compatibility normalization only.
- `src/lib/components/chat/MaterialGraph/`: contract reducer, schema/resume adapters, graph layout, and panel.
- `AssistantForm.svelte`: schema-driven checkpoint form.
- `ResponseMessage.svelte`: one callback seam that appends resume stream output to the existing message.
- `ChatControls.svelte`: Graph tab in the existing chat controls.
- Cypress and pytest/Vitest contract coverage.

No authentication, history persistence, Markdown, file handling, model selection, or base chat composition was replaced.
