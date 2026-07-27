# Immutable GHCR publishing

The project publishes a container only after `Material Graph CI` succeeds for a
push to the default `main` branch. The image source is the exact 40-character
commit recorded by the completed CI run, not the branch tip at publish time.

Published references use only this form:

```text
ghcr.io/ai4s-fiber/material-graph-openwebui:sha-<40-character-commit>
```

GitHub organization package visibility must be configured as public once by a
package administrator. The workflow does not change package visibility. A separate
read-only job, with an empty Docker credential store and no package-write or OIDC
permission, verifies anonymous registry access, the exact digest, and the keyless
signature before succeeding. The workflow never creates or updates `latest`.
Production deployments should pin the registry digest returned by GHCR:

```text
ghcr.io/ai4s-fiber/material-graph-openwebui@sha256:<digest>
```

The publishing job uses only the repository-scoped `GITHUB_TOKEN` and GitHub
OIDC. Its permissions are limited to reading source, writing the package, and
creating provenance/SBOM attestations. No runtime API, NAS, host, deployment, or
server credentials belong in this workflow.

The release build fixes the runtime identity at UID/GID `10001:10001`, pins
`uv==0.11.32`, and initializes `/app/backend/data` with that ownership before
declaring it as a volume. A fresh Docker named volume therefore starts writable by
the non-root process. Existing or bind-mounted host paths must be prepared with the
same numeric ownership before the container starts; the image never escalates to
root to repair host permissions.

## Minimal production runtime

The container uses separate frontend and Python dependency builders plus a
Wolfi runtime-assembly stage. Node, the Chainguard Python 3.14 development image,
and the Chainguard Wolfi base are pinned by immutable SHA-256 index digests in
the Dockerfile. The final `scratch` stage receives only the assembled runtime
filesystem, frontend build, application source, and hash-locked production
virtual environment; it inherits no package-manager or builder configuration.
Installation uses `--require-hashes --no-deps`, so every Python artifact must
match the reviewed lock. Compiler and development packages never cross the
builder boundary. The runtime pins Wolfi's `libpq-18`, `libxml2-16`, and
`libxslt` packages, then removes `apk` before the final copy. It contains no
`git`, `curl`, `jq`, `ffmpeg`, `gcc`, `make`, Rust toolchain, `pip`, package
manager, or test tooling.

The Material Graph deployment delegates local model inference, embeddings,
reranking, browser automation, and document extraction to dedicated services. Its
production dependency lock therefore omits Torch, ONNX, Whisper, Playwright, and
alternate vector database clients. PostgreSQL/pgvector is the only in-process
vector backend. Both SQLAlchemy execution paths explicitly use psycopg3; the
production build compiles its C implementation against Wolfi `libpq` and does
not ship psycopg2 or the self-contained `psycopg-binary` wheel. ChromaDB support
and `python-jose` were removed rather than
suppressed because their dependency chains contained unfixed Critical/High
advisories. No wildcard vulnerability ignore or relaxed severity threshold is
used.

Every pull request and every published digest must pass the same Grype gate that
rejects `high` and `critical` findings, including findings without an available
upstream fix. Passing release images receive GitHub build provenance, an SPDX JSON
SBOM attestation, and a Sigstore Cosign keyless signature bound to this workflow's
GitHub OIDC identity. The SBOM is also retained as a workflow artifact for 30 days.
Upstream Release and PyPI workflows remain disabled and are not prerequisites for
container publishing. The workflow builds and publishes only; it does not deploy to
any server.

## Formatting ownership

This product fork owns formatting for the Material Graph integration surface: its
graph components, assistant form bridge, preview and Cypress contract, release
workflows, and product release documentation. Frontend CI runs a read-only Prettier
check over those paths and still builds the complete Open WebUI production frontend.

The remaining Open WebUI source tree is upstream-owned and is not mechanically
rewritten by this project's CI. Upstream formatting drift must not make an otherwise
unchanged Material Graph release mutate unrelated application files.
