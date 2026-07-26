# Open WebUI Release Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish the Material Graph Open WebUI image as a reproducible non-root container with vulnerability gating, keyless signing, and an independent anonymous verification boundary.

**Architecture:** Keep the existing Open WebUI Dockerfile and workflow-run publishing model. Harden the final image to UID/GID 10001, preserve writable named-volume initialization for `/app/backend/data`, pin the `uv` installer, and extend the existing immutable GHCR workflow with pinned actions, Grype, Cosign, and a separate credential-free verification job.

**Tech Stack:** Docker BuildKit, GitHub Actions, GHCR, Grype, SPDX SBOM, GitHub artifact attestations, Sigstore Cosign, pytest, Vitest, SvelteKit/Vite.

---

### Task 1: Freeze the release contract in tests

**Files:**

- Create: `test/integrations/test_material_graph_release_contract.py`
- Modify: `.github/workflows/material-graph-ci.yml`

- [ ] **Step 1: Add failing static contract tests**

Assert that the Dockerfile fixes UID/GID 10001, pins `uv`, creates and declares the data volume, and that both Material Graph workflows use full commit SHAs. Assert the image workflow blocks `high` vulnerabilities, signs the digest with Cosign, and verifies public access in a separate job without package-write or OIDC permissions.

- [ ] **Step 2: Run the focused release contract test**

Run: `python -m pytest test/integrations/test_material_graph_release_contract.py -q`

Expected: failures for the current root defaults, floating action tags, absent Grype/Cosign steps, and inline anonymous verification.

- [ ] **Step 3: Add the contract test to Material Graph CI**

Run the new release contract beside `test/integrations/test_material_graph_pipe.py` so publishing cannot be triggered by a CI run that skipped supply-chain checks.

### Task 2: Make the image non-root and reproducible

**Files:**

- Modify: `Dockerfile`

- [ ] **Step 1: Set immutable release defaults**

Set `UID=10001`, `GID=10001`, and `UV_VERSION=0.11.32`; reject root UID/GID during the image build and install exactly `uv==${UV_VERSION}`.

- [ ] **Step 2: Create writable runtime directories**

Create `/home/app`, `/home/app/.cache/chroma`, and `/app/backend/data` with UID/GID 10001 ownership and restrictive writable permissions. Keep copied frontend/backend assets owned by the runtime identity.

- [ ] **Step 3: Declare and run the volume as non-root**

Declare `VOLUME ["/app/backend/data"]` after ownership setup and keep the final `USER $UID:$GID`, ensuring a fresh Docker named volume inherits the image directory ownership.

- [ ] **Step 4: Run the release contract test**

Run: `python -m pytest test/integrations/test_material_graph_release_contract.py -q`

Expected: Dockerfile assertions pass while workflow assertions remain red.

### Task 3: Harden the immutable image workflow

**Files:**

- Modify: `.github/workflows/material-graph-image.yml`
- Modify: `.github/workflows/material-graph-ci.yml`
- Modify: `docs/container-publishing.md`

- [ ] **Step 1: Pin every Material Graph action**

Replace action major-version tags with reviewed 40-character commit SHAs, including checkout, Python/Node setup, Buildx, GHCR login, build/push, Anchore, attestation, artifact upload, and Cosign installer actions.

- [ ] **Step 2: Enforce the non-root build contract**

Pass `UID=10001`, `GID=10001`, and `UV_VERSION=0.11.32` as release build arguments in addition to the immutable source SHA.

- [ ] **Step 3: Add the Grype high-severity gate**

Scan the pushed digest with `anchore/scan-action`, `severity-cutoff: high`, and `fail-build: true` before attestations and signing.

- [ ] **Step 4: Add keyless Cosign signing**

Install Cosign from a pinned action and sign the exact image digest with GitHub OIDC using `cosign sign --yes`.

- [ ] **Step 5: Isolate anonymous verification**

Expose only the digest as a publish-job output. Add a dependent `verify-public` job with read-only permissions, a fresh Docker config, anonymous GHCR token/manifest validation, and keyless signature verification against the repository workflow identity.

- [ ] **Step 6: Document the acceptance boundary**

Document UID/GID 10001, fresh-volume ownership, pinned `uv`, high/critical vulnerability rejection, keyless signing, and the independent anonymous verification job without changing package visibility or deploying anything.

### Task 4: Validate and commit

**Files:**

- Test: `test/integrations/test_material_graph_release_contract.py`
- Test: `src/lib/components/chat/MaterialGraph/tests/*.test.ts`

- [ ] **Step 1: Format only Material Graph frontend files**

Run Prettier only against `src/lib/components/chat/MaterialGraph/**/*.{ts,svelte}` and confirm no unrelated frontend file changes.

- [ ] **Step 2: Run focused backend/release tests**

Run: `python -m pytest test/integrations/test_material_graph_pipe.py test/integrations/test_material_graph_release_contract.py -q`

Expected: all focused tests pass.

- [ ] **Step 3: Run Material Graph Vitest**

Run: `npm run test:frontend -- --run src/lib/components/chat/MaterialGraph/tests`

Expected: all Material Graph Vitest files pass.

- [ ] **Step 4: Build the production frontend**

Run: `npm run build`

Expected: SvelteKit production build exits successfully.

- [ ] **Step 5: Validate diff and commit without pushing**

Run `git diff --check`, confirm no package visibility or deployment mutation, then commit all release-hardening changes on `codex/openwebui-release-hardening` without pushing.
