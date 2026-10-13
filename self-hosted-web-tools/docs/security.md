# Security model and limits

This is a single-principal local service. Anyone holding `API_KEY` can use all
permitted tools, see sessions and retrieve all saved artifacts. Do not share one
deployment among mutually untrusted users. There is no per-user ownership layer.

## Outbound network

Only public HTTP/HTTPS destinations on configured ports pass URL/address policy.
Credentials, unsupported schemes, scoped IPv6, localhost, private/link-local,
metadata, reserved and multicast addresses are blocked. All DNS answers must be
public; a mixed public/private result fails closed. The TCP connector receives
only checked IP literals, preventing a second resolution between check and use.
TLS certificates/SNI and HTTP Host use the original domain. Every new connection
checks again; existing pooled sockets remain connected to their original checked IP.
Redirects are separately validated, capped at five, and do not forward cookies or
authorization. Environment proxies are ignored. Shared HTTP clients retain no cookies.

Chromium documents and subresources are fulfilled through that same client.
Service workers and WebSockets are blocked. A dead proxy and disabled unproxied
WebRTC prevent missed traffic from having normal browser egress. No tool exposes
arbitrary JavaScript. GET-only traffic means many modern interactive sites will
not work. Browser navigation can still cause server-side effects through GET;
the service cannot infer a site's semantics or guarantee absence of remote effects.

Compose adds an OUTPUT firewall in an isolated shared network namespace. It blocks
private/reserved IPv4 and IPv6 outbound, except Docker DNS, the trusted SearXNG
address/port, and the local API health port. Public egress is TCP 80/443. The app has
no network-admin capability. The firewall sidecar alone has `NET_ADMIN`, no API,
and a read-only filesystem. Changing ports, private subnet or SearXNG IP requires
coordinated edits to firewall and Compose. SearXNG uses its own outbound namespace;
it is a trusted application dependency, not a general browsing bypass.

Test fixtures may allow exact origins only under `ENVIRONMENT=test`. Production
must never be deployed with that environment. Fixture tests run on a separate
local or isolated container network, not through production firewall exceptions.

## Files and resources

Clients supply names, never directories. Filename validation rejects traversal,
Windows device names/alternate streams, hidden files, separators and control bytes.
UUID storage names and no-replace publication prevent overwrites. Streams and
screenshots share a serialized quota; cancellation cleans partial/published files.
Startup removes abandoned `.partial` files. The download directory must be owned
only by the application, not writable by other processes; external filesystem
mutation/symlink races are outside the threat model. Use one application worker.

Direct streams cap at 100 MiB and total artifacts at 1 GiB by default. Browser
responses and link-download buffers cap at 10 MB before Blob capture. Browser
downloads temporarily use memory and Chromium's task directory, cleaned after
capture and context shutdown. Fetch bodies cap before parsing. Compressed replies
that ignore requested identity encoding are rejected to avoid decompression bombs.
All tools have a wall-clock deadline; request bodies cap at 64 KiB, including
chunked requests. Session counts, idle expiry, container memory/pid/tmp limits
provide additional bounds. There is no comprehensive per-client rate limiter yet.

Artifact retrieval forces an attachment and adds `nosniff` and sandbox headers.
PDF reading accepts only managed artifact IDs and checks the actual PDF header.
The parser receives no caller-selected paths, URLs, passwords or executable code.
Encrypted PDFs are rejected; embedded scripts/attachments are not executed.
PDF input defaults to 20 MiB, reads to at most 20 pages per call, and extracted text
shares the global response/character budgets. pypdf stream decoding is capped at
10 MB per stream with bounded page-tree traversal. Each parse runs in one subprocess
under the tool's wall-clock deadline, killed and reaped on cancellation. At most
one parser runs at a time. Linux workers additionally cap address space at 512 MiB
and CPU time at 60 seconds; native Windows has no per-process memory ceiling and
relies on input/decoder limits and the killable timeout. These restrictions reduce
resource exhaustion risk; the parser is not a separate OS security sandbox.

The application never executes downloaded content. Browser sessions are ephemeral;
only completed artifacts and SQLite metadata persist. Back up that volume together.

## Actions, authentication and content

Link navigation skips JavaScript handlers. Filling controls and clicking non-links
can trigger state changes and require a separate human credential to issue an
exact, one-use, 60-second grant. POST and other non-GET browser requests remain
blocked after approval. Keep the human credential inaccessible to agents.
The approval system does not classify purchases or infer user consent from page text.

Bearer authentication covers REST, MCP, OpenAPI/docs and artifact bytes; only
health is public. MCP validates Host/Origin using the official SDK. No permissive
CORS is installed. TLS/OAuth are not implemented locally. Logs omit URLs at INFO
and do not emit tool arguments or body data; operator DEBUG logs need care.

Web text and files may contain prompt injection. Responses mark extracted/snapshot
content untrusted, but consuming applications must enforce that boundary. Browser
engine exploits remain possible; container isolation and updates reduce risk but
do not provide a formally verified sandbox.

## Secure LAN access

Prefer a TLS reverse proxy on a restricted LAN/VPN, retaining bearer authentication.
Keep the app's localhost publication and proxy it; firewall clients at the proxy,
configure rate limits, and set `MCP_ALLOWED_HOSTS` to the exact proxy hostname.
For browser-origin MCP clients, extend the SDK's explicit origin allowlist in
`mcp/server.py` and narrowly configure CORS for that client. Never use wildcard
origins. Dockerized agent clients can join an explicitly private network and use
the egress service hostname with a matching MCP host allowlist. Do not publish
SearXNG or expose the API to the internet. Per-client ownership/OAuth must precede
multi-user deployment.
