# Configuration

`Settings` loads environment variables and `.env`. Environment values override
the file. Unknown entries such as `SEARXNG_SECRET` belong to other services.
`scripts/init_env.py` generates all three independent secrets without printing them.

| Variable | Default / purpose |
| --- | --- |
| `API_KEY` | Required, at least 24 characters; bearer credential for all clients |
| `HUMAN_APPROVAL_KEY` | Optional, distinct, at least 24 characters; blank disables grants |
| `SEARXNG_SECRET` | Required by Compose; SearXNG server secret |
| `APP_HOST` | Native default `127.0.0.1`; forced to `0.0.0.0` inside Compose |
| `APP_PORT` | `8000`; Compose uses it as the published host port and keeps container port 8000 |
| `SEARXNG_BASE_URL` | Native `http://127.0.0.1:8080`; Compose `http://searxng:8080` |
| `BROWSER_ENABLED` | `true`; false omits all browser tools and skips Chromium startup |
| `BROWSER_HEADLESS` | `true` |
| `BROWSER_MAX_SESSIONS` | `3`, global task context cap |
| `BROWSER_SESSION_TIMEOUT_SECONDS` | `900`, idle expiry; cleanup every 10 seconds |
| `BROWSER_MAX_RESPONSE_BYTES` | `10000000`, bounded browser responses/link downloads |
| `DOWNLOAD_DIRECTORY` | Native `data/downloads`; Compose `/data/downloads` |
| `DATABASE_URL` | Native `sqlite:///data/webtools.db`; Compose `sqlite:////data/webtools.db` |
| `MAX_DOWNLOAD_SIZE_MB` | `100` MiB per stored artifact |
| `STORAGE_QUOTA_MB` | `1024` MiB across downloads and screenshots |
| `HTTP_REQUEST_TIMEOUT_SECONDS` | `30`, upstream per-network-operation timeout |
| `TOOL_TIMEOUT_SECONDS` | `60`, wall-clock deadline for each tool, including streams |
| `MAX_FETCH_CHARS` | `12000`, global extracted/snapshot character cap |
| `MAX_TOOL_RESPONSE_CHARS` | `24000`, aggregate serialized data budget; lists/text shorten with truncation flags |
| `MAX_FETCH_BYTES` | `2000000`, fetched body cap before parsing |
| `MAX_SEARCH_BYTES` | `2000000`, SearXNG response cap |
| `PDF_MAX_FILE_SIZE_MB` | `20` MiB maximum stored PDF accepted for reading (1–100) |
| `PDF_MAX_PAGES_PER_CALL` | `20` pages maximum per read (1–100); default selection is up to 5 |
| `ALLOWED_PORTS` | JSON `[80,443]`; firewall must also permit any changed ports |
| `MCP_ALLOWED_HOSTS` | JSON localhost, loopback host patterns; needed for MCP host validation |
| `LOG_LEVEL` | `INFO`, JSON events; access logging disabled to avoid URLs/secrets |
| `ENVIRONMENT` | `production` |
| `TEST_ALLOWED_ORIGINS` | JSON `[]`; exact fixture origins, only allowed in test environment |

Compose containers use a named storage volume. To inspect safely:

```bash
docker compose exec app python -c "from pathlib import Path; print([p.name for p in Path('/data/downloads').iterdir()])"
```

Native startup example (bash):

```bash
export APP_HOST=127.0.0.1
export DOWNLOAD_DIRECTORY=data/downloads
export DATABASE_URL=sqlite:///data/webtools.db
export SEARXNG_BASE_URL=http://127.0.0.1:8080
python -m web_tools
```

Use an separately reachable trusted SearXNG instance for native development; the
default Compose instance intentionally has no host port. Its YAML enables JSON
and Bing, Google and DuckDuckGo, and disables rate limiting on the unexposed internal service.
Application limits
still apply. The container's public search traffic is subject to upstream limits.

`requirements.lock` pins runtime and development dependencies for repeatable
validation. `pyproject.toml` defines compatible ranges for packaging. Regenerate
the lock only after testing reviewed updates. For reproducible image deployment,
the SearXNG digest is pinned in Compose and recorded in validation.
