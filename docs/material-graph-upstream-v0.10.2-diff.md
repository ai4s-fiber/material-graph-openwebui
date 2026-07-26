# Open WebUI v0.10.2 upstream difference audit

Baseline: upstream tag `v0.10.2`, commit `ecd48e2f718220a6400ecf49eafd4867a38feb10`.

## Provenance and licensing

The imported upstream tree retains `LICENSE`, `LICENSE_NOTICE`, `LICENSE_HISTORY`, changelog, and Git-side project history. Material Graph additions use the upstream license for modified files. Dagre is the only newly declared runtime package and is MIT licensed; SvelteFlow was already upstream.

## Minimal synchronization seams

The integration is intentionally isolated in newly added `integrations/` and `src/lib/components/chat/MaterialGraph/` modules. Upstream chat UI changes are limited to:

1. `ChatControls.svelte`: import/read the latest graph snapshot and expose a Graph side-panel tab.
2. `ResponseMessage.svelte`: render `AssistantForm` and append its resumed token/status events to the existing message.
3. `+layout.svelte`: permit the isolated Material Graph preview route.
4. `package.json` and lockfile: add `@dagrejs/dagre`.

The integration does not fork or rewrite message streaming, Markdown rendering, chat history, authentication, model selection, files, or the composer.

## Future upstream sync procedure

The fork keeps `origin` pointed at `ai4s-fiber/material-graph-openwebui` and
`upstream` pointed at `open-webui/open-webui`. Sync a reviewed upstream release
on a dedicated branch; never merge a moving upstream default branch directly
into the Material Graph branch.

```powershell
git fetch upstream --tags
git switch -c sync/open-webui-vX.Y.Z material-graph-v0.10.2
git rebase --onto upstream/vX.Y.Z ecd48e2f718220a6400ecf49eafd4867a38feb10
```

1. Confirm the selected upstream tag and commit before rebasing.
2. Reconcile the isolated `MaterialGraph` directory and Pipe unchanged where possible.
3. Reconcile only the three UI seams above against upstream component signatures.
4. Refresh the lockfile for Dagre without upgrading unrelated dependencies.
5. Run Pipe pytest, Material Graph Vitest, Cypress contract screenshot, Svelte check, and production build.
6. Review `git diff --name-only upstream/vX.Y.Z...HEAD` and reject unrelated Open WebUI churn.
7. Push the sync branch and merge only after review.

The inherited `release.yml` and `release-pypi.yml` workflows are stored with a
`.disabled` suffix in this fork. Do not restore their executable `.yml` names
until maintainers have reviewed publishing targets, permissions, secrets, and
fork-specific versioning. Project-specific security CI should be added and
reviewed separately before either release workflow is re-enabled.

## Current hardening delta

This hardening adds version aliases, topology-preserving state, explicit terminal semantics, stream-first same-checkpoint resume, run-id validation, deterministic idempotency, arbitrary object JSON Schema controls, focused tests, and a rejection visual regression scenario. All changes remain below `open-webui/**`.
