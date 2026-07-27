# Security Policy

This repository is the Open WebUI frontend dependency fork used by
[Material Graph Studio](https://github.com/ai4s-fiber/material-graph-studio).
Material Graph security reports have one intake point so that frontend,
backend, deployment, and data-access impact can be assessed together.

## Supported code

Security fixes target the current `main` branch and immutable image digest used
by the current Material Graph Studio release. Historical branches, upstream
tags, and unreferenced package versions are not independently supported.

## Report privately

Do not open a public issue, pull request, discussion, or log excerpt for a
suspected vulnerability.

Use the main project's
[private security advisory form](https://github.com/ai4s-fiber/material-graph-studio/security/advisories/new).
If GitHub does not make that form available to you, contact an `ai4s-fiber`
organization owner through an already established private channel and ask for
a private reporting route. Do not disclose the finding publicly while access
is being arranged.

Reports first observed in the Material Graph deployment should still use this
single intake point, including reports that may originate in upstream Open
WebUI. The maintainers will determine whether and how to coordinate with the
upstream project.

## Never include secrets

Do not submit real or recoverable:

- API keys, model tokens, MinerU tokens, or reranker credentials;
- NAS or QuickConnect addresses, usernames, passwords, cookies, or file links;
- database DSNs, HMAC secrets, session keys, or secret-file contents;
- complete `.env` files, environment dumps, deployment manifests, or command
  history containing credentials;
- production data or documents, experimental data, user conversations, or
  unredacted logs.

Revoke and rotate a credential immediately if it was exposed before or during
reporting. Redaction is not a substitute for rotation.

## Safe report contents

After removing sensitive data, include:

- the affected source commit and image digest;
- the affected Material Graph Studio release or deployment component;
- impact, preconditions, and the security boundary crossed;
- reproduction steps using synthetic data and placeholder credentials;
- the smallest relevant redacted logs or screenshots;
- any temporary mitigation already applied.

The main-project maintainers will acknowledge the report, coordinate affected
components, and disclose fixes only after a patched release or mitigation is
available.
