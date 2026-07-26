# Immutable GHCR publishing

The project publishes a container only after `Material Graph CI` succeeds for a
push to the default `main` branch. The image source is the exact 40-character
commit recorded by the completed CI run, not the branch tip at publish time.

Published references use only this form:

```text
ghcr.io/ai4s-fiber/material-graph-openwebui:sha-<40-character-commit>
```

GitHub organization package visibility must be configured as public once by a
package administrator. The workflow verifies an anonymous pull and exact digest
before succeeding. It never creates or updates `latest`. Production deployments should
pin the registry digest returned by GHCR:

```text
ghcr.io/ai4s-fiber/material-graph-openwebui@sha256:<digest>
```

The publishing job uses only the repository-scoped `GITHUB_TOKEN` and GitHub
OIDC. Its permissions are limited to reading source, writing the package, and
creating provenance/SBOM attestations. No runtime API, NAS, host, deployment, or
server credentials belong in this workflow.

Each published image receives GitHub build provenance and an SPDX JSON SBOM
attestation. The SBOM is also retained as a workflow artifact for 30 days.
Upstream Release and PyPI workflows remain disabled and are not prerequisites
for container publishing.