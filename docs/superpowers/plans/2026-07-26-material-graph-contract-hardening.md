# Material Graph Contract Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the Open WebUI Material Graph integration against versioned backend events, checkpoint resume streaming, non-success terminal outcomes, and arbitrary JSON Schema forms while retaining a minimal v0.10.2 patch.

**Architecture:** Normalize every backend event into a stable frontend status contract inside the Pipe, keeping full `WorkflowDefinition` topology separate from authoritative runtime state. Resume submissions use a shared client adapter that prefers `/runs/{run_id}/resume/stream`, consumes SSE into the existing Open WebUI event stream, and falls back to legacy `/resume` only when the streaming route is unavailable without inventing a run id. Form schema normalization and validation remain isolated from rendering so Vitest can cover the contract directly.

**Tech Stack:** Python/httpx/pytest, TypeScript/Svelte, Vitest, Cypress, SvelteFlow/Dagre, Open WebUI v0.10.2.

---

### Task 1: Versioned Pipe event normalization

**Files:** `integrations/material_graph_pipe.py`, `test/integrations/test_material_graph_pipe.py`

- [ ] Add failing pytest cases for v1/v2 envelopes covering WorkflowDefinition, node state, token/delta, log, assistant_form, and terminal outcome events.
- [ ] Run the focused pytest module and confirm the new compatibility cases fail.
- [ ] Implement envelope unwrapping, aliases, version preservation, full-workflow snapshot merging, authoritative current-node forwarding, and non-success terminal normalization.
- [ ] Re-run the Pipe tests and confirm they pass.

### Task 2: Frontend workflow state reducer and terminal semantics

**Files:** `src/lib/components/chat/MaterialGraph/{types.ts,contract.ts,Node.svelte,View.svelte,tests/materialGraph.test.ts}`

- [ ] Add failing Vitest cases proving topology persists across partial state events, only authoritative events select the active node, and non-success outcomes never map to success.
- [ ] Implement the reducer and status predicates, then wire the panel and nodes to explicit active and outcome fields.
- [ ] Re-run the focused Vitest suite and confirm it passes.

### Task 3: Streaming checkpoint resume adapter

**Files:** `src/lib/components/chat/MaterialGraph/{resume.ts,tests/resume.test.ts}`, `src/lib/components/chat/Messages/ResponseMessage/AssistantForm.svelte`

- [ ] Add failing Vitest cases for stream-first resume, 404/405 fallback, same-run enforcement, SSE token/status forwarding, and duplicate-submit idempotency keys.
- [ ] Implement a fetch adapter that posts the same payload and idempotency key to /resume/stream, parses SSE, rejects mismatched run ids, and falls back only for route-unavailable responses.
- [ ] Connect resume statuses to the existing event path and prevent repeat submissions after acceptance.
- [ ] Re-run the focused tests and confirm they pass.

### Task 4: Arbitrary JSON Schema form normalization and validation

**Files:** `src/lib/components/chat/MaterialGraph/{formSchema.ts,tests/formSchema.test.ts,types.ts}`, `src/lib/components/chat/Messages/ResponseMessage/AssistantForm.svelte`

- [ ] Add failing tests for required fields, numeric ranges, enum, array multi-select, boolean, descriptions, defaults, and field errors.
- [ ] Implement schema normalization, deterministic validation, typed serialization, and accessible controls.
- [ ] Re-run focused tests and confirm they pass.

### Task 5: Cross-layer contract and visual scenarios

**Files:** `cypress/fixtures/material-graph-stream.txt`, `cypress/e2e/material-graph.cy.ts`

- [ ] Extend fixtures with full workflow, partial transitions, schema form, resumed SSE, and non-success terminal events.
- [ ] Add assertions for graph persistence, active-node movement, fallback, validation, idempotency, and terminal styling.
- [ ] Capture a deterministic regression screenshot through Cypress.

### Task 6: Upstream v0.10.2 audit and production verification

**Files:** `docs/material-graph-integration.md`, `docs/material-graph-upstream-v0.10.2-diff.md`

- [ ] Compare the integration patch with upstream v0.10.2 commit ecd48e2f718220a6400ecf49eafd4867a38feb10.
- [ ] Document license/history preservation, dependency additions, patch seams, sync guidance, and confirmation that chat UI was extended rather than rewritten.
- [ ] Run pytest, Vitest, npm run check, and npm run build; fix only Material Graph integration defects.
- [ ] Confirm every changed path remains under open-webui, review, and commit without pushing or deploying.
