# Validation record

Validated on October 12, 2026 (America/New_York). Tests use Python 3.12; the Docker
image uses Linux amd64 and the locked dependency set.

| Check | Observed result |
| --- | --- |
| Windows Pytest | 64 passed, 1 dependency deprecation warning |
| Linux image Pytest, `--network none` | 64 passed, 1 dependency deprecation warning |
| Ruff lint and formatting | passed |
| Python sdist and wheel | built successfully; sdist contained no `.env`, `.tmp` or `.venv` entries |
| Compose build/start | app, SearXNG and egress containers started and became healthy |
| Liveness/readiness | HTTP 200; SearXNG, SQLite, managed storage and Chromium healthy |
| Official MCP SDK client | initialization, discovery and invocation passed in tests and over live HTTP |
| Live public search | real SearXNG/Bing results returned through MCP |
| Live fetch | `https://example.com` extracted successfully |
| Live direct download | 577-byte HTML file persisted with verified SHA-256 |
| Live Chromium | public page opened, accessibility snapshot captured, context closed |
| Artifact persistence | an earlier file survived app container recreation; metadata and served bytes matched SHA-256 |
| Artifact authorization | unauthenticated read returned 401 |
| Network policy | cloud metadata URL returned `blocked_url` without an outbound request |
| Container firewall | blocked direct socket attempts to metadata/private IPs and public port 22 |
| Deterministic research workflow | local fixture search → fetch → browser → approved fill/click → link → browser download → inspect/list → screenshot → close |

SearXNG initially used default providers that returned CAPTCHA, rate-limit and
access-denied responses. The configured engine set now enables Bing, Google and
DuckDuckGo. Bing returned results during final public validation. DuckDuckGo still
reported CAPTCHA, which appeared in successful responses' `warnings`. No CAPTCHA
bypass or fixture substitution was used. Provider availability and search quality
remain upstream-dependent; a successful check is an observation, not a guarantee.

Initial Docker readiness exposed an internal address selection issue: two shared
networks allowed Docker DNS to select SearXNG's outward address, blocked by the
firewall. Separate outward networks and reserved internal addresses fixed it. The
final stack passed readiness and the complete public smoke test.

The test-client warning comes from Starlette's deprecation of its HTTPX-based test
client integration. The official MCP SDK still uses HTTPX. It does not indicate a
failed test or a runtime feature failure. On this Windows host, the execution
sandbox blocked asyncio's loopback sockets; socket/browser tests required execution
outside that sandbox. The Linux suite used an isolated container with external
networking disabled.

## Reproduce

From the repository directory with its Python environment installed:

```bash
pytest -q
ruff check src tests scripts
ruff format --check src tests scripts
python -m build
docker compose config --quiet
docker compose up --build -d --wait
python scripts/smoke_test.py --public
docker compose ps
```

Windows isolated Linux suite (PowerShell):

```powershell
docker run --rm --network none `
  --mount "type=bind,source=$((Get-Location).Path)\tests,target=/app/tests,readonly" `
  self-hosted-web-tools-app python -m pytest -q -p no:cacheprovider /app/tests
```

The production firewall intentionally denies ephemeral private fixture ports; run
the deterministic suite in the isolated image or natively, not in the production
application's shared network namespace.

SearXNG image pinned in Compose:
`searxng/searxng@sha256:a7f9188cc7fa8b6b037e0d85709c0dced8f05d0eba84145eb7fe7027a4c00850`.
Update deliberately after reviewing/testing upstream changes.

## Remaining work

1. Per-client session/artifact ownership and rate limits before multi-user use.
2. Richer explicitly approved browser downloads, multiple tabs and more accessible
   element representations (current element enumeration covers the main document).
3. Cached search/page results and provider diagnostics to reduce upstream requests.
4. PDF/Office extraction, authenticated profiles, scheduled jobs and observability.

Current restrictions: one application worker, one tab per task session, GET-only
browser traffic, no public deployment/OAuth, no browser button/script download,
no persisted browser profiles, and no model-specific orchestration. All 14 exposed
tools contain working implementations; these future capabilities are not stubs.
