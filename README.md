# Material Graph Open WebUI

> This repository is the frontend dependency fork for
> [Material Graph Studio](https://github.com/ai4s-fiber/material-graph-studio),
> the single entry point for the complete product.

## Repository role

This fork contains the Open WebUI interface and integration layer used by Material Graph Studio:

- conversational material-research workspace;
- structured human-input forms rendered inside assistant messages;
- full workflow graph, live node state, elapsed time, and execution logs;
- SSE event handling and the Material Graph API adapter.

Backend services, LangGraph workflows, knowledge engineering, deployment, release tracking, and
cross-module issues belong in
[`ai4s-fiber/material-graph-studio`](https://github.com/ai4s-fiber/material-graph-studio).

## Where to contribute

| Change | Repository |
| --- | --- |
| Open WebUI components or frontend-only integration | This fork |
| API, graph runtime, retrieval, data, deployment, or cross-module behavior | [Material Graph Studio](https://github.com/ai4s-fiber/material-graph-studio) |
| Generic Open WebUI feature or bug fix | [Upstream Open WebUI](https://github.com/open-webui/open-webui) |

## Upstream relationship

This repository is based on
[`open-webui/open-webui`](https://github.com/open-webui/open-webui).
Upstream changes are synchronized deliberately and reviewed against the Material Graph integration;
this fork is not an independent replacement for Open WebUI.

- [Open WebUI documentation](https://docs.openwebui.com/)
- [Open WebUI source](https://github.com/open-webui/open-webui)
- [Open WebUI releases](https://github.com/open-webui/open-webui/releases)

## Release artifact

Production consumes a digest-pinned, scanned, attested, and signed image from
`ghcr.io/ai4s-fiber/material-graph-openwebui-release`.
The GHCR package is a deployment artifact, not another source repository.

## License and attribution

The fork retains Open WebUI attribution and its applicable licensing terms. Review
[`LICENSE`](./LICENSE) and [`LICENSE_HISTORY`](./LICENSE_HISTORY) before redistributing or modifying
the code. Upstream contribution requirements remain documented in the
[Open WebUI repository](https://github.com/open-webui/open-webui).
