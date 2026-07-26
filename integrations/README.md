# Material Graph Studio integration

Import `material_graph_pipe.py` through Open WebUI Admin > Functions, then set the
Pipe valve `material_graph_api_url` to the browser-reachable Material Graph API
origin. The same value is attached to assistant forms so their checkpoint-resume
request is sent directly to the backend endpoint declared by the SSE contract.

The Pipe is intentionally generic: workflow nodes, edges, logs, form fields and
material/domain labels are passed through unchanged.
