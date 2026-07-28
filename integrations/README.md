# Material Graph Studio integration

The fork image bundles `material_graph_pipe.py` and reconciles it into Open
WebUI's function table during startup. The managed row is idempotent across
restarts, remains inactive only when Open WebUI safe mode is enabled, and
records the source SHA-256 plus image revision in its manifest. No Admin UI
import or signup toggle is required.

Keep the Pipe valve `material_graph_api_url` on the private service URL
`http://material-graph-api:8000`; it must never be browser reachable. Chat calls
are signed from the authenticated Open WebUI user context. Assistant forms use
the same-origin `/api/v1/material-graph` BFF, which verifies the Open WebUI login
and creates a fresh short-lived signature for each checkpoint resume.

Both containers receive `MATERIAL_GRAPH_HMAC_SECRET_FILE` from the orchestrator.
The secret and signed internal header are never emitted to browser events.

The Pipe is intentionally generic: workflow nodes, edges, logs, form fields and
material/domain labels are passed through unchanged.
