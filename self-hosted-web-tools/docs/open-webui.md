# Open WebUI and other clients

Open WebUI supports native Streamable HTTP MCP from version 0.6.31. In
Settings → Admin → Integrations → External Tool Servers, add a connection with
type **MCP (Streamable HTTP)** and server URL `http://127.0.0.1:8000/mcp` when the
backend runs on the same host. Supply a custom header:

```json
{"Authorization":"Bearer YOUR_API_KEY"}
```

Select the tools for the chat/model using your installation's tool controls.
The connection is admin-managed. Use a model/agent capable of tool calls; the
connection itself does not implement research orchestration. See
[official Open WebUI MCP documentation](https://docs.openwebui.com/features/extensibility/mcp/).

A Dockerized Open WebUI backend's `localhost` is its own container. Either use
a deliberate private shared Docker network and `http://egress:8000/mcp`, adding
`egress:*` to `MCP_ALLOWED_HOSTS`, or use a restricted TLS proxy reachable from the
backend. Do not assume a host service bound only to loopback is accessible through
`host.docker.internal` on every platform. Keep the human approval credential out
of Open WebUI/agent tool configuration.

REST clients can use the same bearer credential and flat JSON tool contracts.
`/openapi.json` is authenticated and can be consumed by an OpenAPI tool client.
Swagger's HTML route is also authenticated, so a browser may need a header-aware
client/proxy to load it. Do not weaken API auth to make docs publicly accessible.

Other MCP agents use the same Streamable HTTP URL and bearer header. The official
Python client example in `scripts/smoke_test.py` demonstrates initialization,
discovery and invocation. Configure adapters in OpenClaw/custom agents according
to their supported MCP client transport. No model-specific execution logic is
implemented here, and Ollama alone does not orchestrate tools.
