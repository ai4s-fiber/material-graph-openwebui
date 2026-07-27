# Material Graph Studio integration

Import `material_graph_pipe.py` through Open WebUI Admin > Functions. Keep the
Pipe valve `material_graph_api_url` on the private service URL
`http://material-graph-api:8000`; it must never be browser reachable. Chat calls
are signed from the authenticated Open WebUI user context. Assistant forms use
the same-origin `/api/v1/material-graph` BFF, which verifies the Open WebUI login
and creates a fresh short-lived signature for each checkpoint resume.

Both containers receive `MATERIAL_GRAPH_HMAC_SECRET_FILE` from the orchestrator.
The secret and signed internal header are never emitted to browser events.

The Pipe is intentionally generic: workflow nodes, edges, logs, form fields and
material/domain labels are passed through unchanged.
