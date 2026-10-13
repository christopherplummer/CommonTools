# Self-hosted Web Tools

Search, fetch readable webpages, browse with Chromium, and save downloads through
one authenticated REST/MCP service. Runs without paid APIs or model inference.
An agent application orchestrates the tools; Ollama alone does not manage MCP.

The initial implementation includes 14 tools, SQLite file metadata, persistent
download storage, task browser sessions, bounded responses, and network policy.
See [tool reference](docs/tool-reference.md) for the exact contracts and limits.

## Start with Docker

Prerequisites: Docker Engine with Compose v2 (Docker Desktop in Linux container
mode on Windows), Python 3.12+ for secret generation and local testing, and public
internet access for image/package downloads and search engines.

From the repository directory:

```bash
python scripts/init_env.py
docker compose up --build -d
docker compose ps
```

The initialization command creates an ignored `.env` with unique secrets and
refuses to overwrite one. After initialization the normal startup command is
`docker compose up --build -d`. Chromium and its Linux libraries are installed in
the image; no host Chromium installation is needed for Docker.

The API is published only at `http://127.0.0.1:8000` by default. SearXNG has no host
port. A firewall sidecar gives the application a restricted network namespace.
Only that sidecar receives `NET_ADMIN`; the app runs as a non-root user with all
capabilities dropped, a read-only root filesystem, and no Docker socket.

```bash
curl http://127.0.0.1:8000/health/live
curl http://127.0.0.1:8000/health/ready
docker compose logs --tail 100 app searxng egress
docker compose stop
docker compose down
```

`stop` and `down` retain the `webtools-data` volume. Do not add `--volumes` if you
want to keep downloads and metadata. Recreate the app when recreating the egress
sidecar, since they share a network namespace.

## REST and MCP

All tool routes, artifact reads, OpenAPI, and Swagger require
`Authorization: Bearer <API_KEY>`. Health endpoints are unauthenticated and contain
only dependency status. Each tool uses `POST /api/tools/<tool_name>` with its MCP
arguments as the JSON body.

```bash
curl -H 'Authorization: Bearer YOUR_API_KEY' -H 'Content-Type: application/json' \
  -d '{"query":"Python Playwright documentation","limit":5,"language":"en"}' \
  http://127.0.0.1:8000/api/tools/web_search
curl -H 'Authorization: Bearer YOUR_API_KEY' -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com","max_chars":12000}' \
  http://127.0.0.1:8000/api/tools/web_fetch
curl -H 'Authorization: Bearer YOUR_API_KEY' -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com/manual.pdf","filename":"manual.pdf"}' \
  http://127.0.0.1:8000/api/tools/file_download
```

PowerShell example (read the key from your `.env`, do not paste it into chat):

```powershell
$key = ((Get-Content .env | Where-Object { $_ -like 'API_KEY=*' }) -split '=', 2)[1]
$headers = @{ Authorization = "Bearer $key" }
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/tools/web_search `
  -Headers $headers -ContentType application/json `
  -Body '{"query":"Python Playwright documentation","limit":5}'
```

Configure an MCP client with Streamable HTTP URL `http://127.0.0.1:8000/mcp` and
the same bearer header. The official Python SDK performs initialization, tool
discovery and calls; see `scripts/smoke_test.py` for a complete client. MCP transport
is stateless, while browser sessions remain in the application keyed by explicit
`session_id`. No stdio server, OAuth provider, or model backend is required.

See [Open WebUI setup](docs/open-webui.md), [configuration](docs/configuration.md),
and [security](docs/security.md) before using a different hostname or LAN access.

## Browser and file behavior

`browser_open` returns a session ID. Reuse it across calls, request
`browser_snapshot`, then use the returned element refs. Every new snapshot or
interaction invalidates previous refs; DOM mutations also cause
`stale_reference`. Sessions expire after 900 seconds idle, with cleanup every
10 seconds. There are at most 3 sessions, each with one main tab. Popups close.
Sessions and cookies are task-local and are lost on restart.

Ordinary link navigation skips click handlers. Button clicks and filling inputs
need single-use approval issued with a separate human credential. All browser
HTTP traffic stays GET-only, including approved actions. See the human approval
example in the tool reference. The agent must never possess `HUMAN_APPROVAL_KEY`.

Downloads and viewport screenshots have stable artifact IDs. Files are stored at
`/data/downloads/<id>_<filename>` and metadata at `/data/webtools.db` in the named
volume. `file_inspect` and `file_list` retrieve metadata; authenticated
`GET /api/files/<file_id>/content` retrieves bytes as an attachment. No caller can
choose a directory, execute a file, or overwrite an existing artifact.

Direct downloads stream to disk up to 100 MiB. Browser link downloads use bounded
HTTP bytes (10 MB by default) and a real Chromium Blob download event, then persist
the captured file. Browser button/script downloads and authenticated profiles
are future work. Screenshots are metadata responses, never automatically embedded.

## Development and validation

Linux/macOS:

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements.lock
pip install -e . --no-deps
python -m playwright install --with-deps chromium
pytest -q
ruff check src tests scripts
ruff format --check src tests scripts
python -m build
```

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.lock
.\.venv\Scripts\python -m pip install -e . --no-deps
.\.venv\Scripts\python -m playwright install chromium
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\ruff check src tests scripts
.\.venv\Scripts\ruff format --check src tests scripts
.\.venv\Scripts\python -m build
```

Native development requires a running SearXNG URL and writable local storage:
override `SEARXNG_BASE_URL`, `DOWNLOAD_DIRECTORY`, `DATABASE_URL`, and
`APP_HOST=127.0.0.1` when using `python -m web_tools`. The sample `.env` is for
Docker; `/data` paths are container paths. Keep one application worker because
browser sessions, quotas and approvals live in that process.

The suite requires no public websites. It uses mocked search normalization,
real local HTTP fixtures, real Chromium, persistent SQLite and the official MCP
client. `pytest -q -m 'not browser'` omits Chromium-dependent tests.

Optional live smoke test against the running stack:

```bash
python scripts/smoke_test.py
python scripts/smoke_test.py --public
```

The `--public` test performs real search, fetching, downloading, and browsing.
Empty live search results fail that check. No fixture response replaces a failed
public test. See [validation record](docs/validation.md) for this implementation's
observed results.

## Troubleshooting and next work

If startup fails, check `docker compose logs --tail 100`. A missing API key or
short secret prevents startup. `421 Invalid Host` means the MCP hostname is absent
from `MCP_ALLOWED_HOSTS`. `403` from SearXNG can mean JSON format is disabled.
Readiness returns `503` when SearXNG JSON, SQLite, writable storage, or the configured
browser is unavailable. Engine rate limits can cause empty search results even
when JSON API health is good. See dependency statuses and logs.

The firewall uses subnet `172.30.95.0/24`; choose a different unused subnet and
matching SearXNG/firewall IP if it conflicts with a local network. Kernel/network
errors in `egress` must be fixed before starting the app. Docker deployment uses
IPv4 outbound; native execution also supports public IPv6. Custom outbound ports
need changes to both application configuration and the firewall.

The service trusts one API principal. It has no per-user isolation, OAuth, job
queue, caching, PDF extraction, persistent authenticated browser profiles, or
arbitrary JavaScript tool. Next priorities are per-client ownership and rate
limits, richer download actions with explicit approvals, and extraction/caching.
Fetched content can contain prompt injection; clients must treat it as data.
