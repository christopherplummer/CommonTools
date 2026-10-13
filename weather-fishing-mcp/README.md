# Weather & Fishing MCP

A self-hosted Python MCP server that retrieves bounded, structured weather,
marine, tide/current, astronomy, solunar and marine-species information. It uses
the official MCP SDK and performs no model inference. Provider adapters are
independent; `collect_conditions` retains successful results when another request
fails. Production code never imports test fixtures or substitutes model memory.

**Implemented:** NWS, NOAA CO-OPS, NOAA NCEI CDO v2, NOAA NDBC,
NOAA Fisheries official species pages, and SolunarForecast monthly tables.
NCEI requires your token. Solunar retrieval is gated pending your actual rights
review. **Planned and disabled:** Met Office, BOM, Tides4Fishing (tides only), and
the licensed timeanddate astronomy API. These plans are not implemented adapters.

Read [provider review and coverage](docs/providers.md), [tool contracts](docs/tools.md)
and [actual validation results](docs/validation.md). This release is an integration
foundation, not a claim of worldwide coverage or production readiness.

## Setup

Python 3.12+ is required. Commands below run from this project directory.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.lock
.venv\Scripts\python -m pip install -e . --no-deps
Copy-Item .env.example .env  # first setup only; preserve an existing .env
```

Linux/macOS equivalents use `.venv/bin/python`. `requirements.lock` pins the
tested environment, including development dependencies. To resolve new versions,
use `pip install -e '.[dev]'`, run checks, then regenerate the lock with
`python scripts/lock_dependencies.py`. Do not copy keys into source, prompts or logs.

Set `WF_USER_AGENT` to identify your application and contact. Set
`WF_NCEI_TOKEN` after obtaining a [CDO token](https://www.ncei.noaa.gov/cdo-web/token).
Absent credentials produce `unavailable`; no registration or paid access is assumed.

SolunarForecast's [terms](https://solunarforecast.com/termsofuse.aspx) restrict
commercial use and redistribution. Leave `WF_SOLUNAR_PERMISSION_REFERENCE` empty
unless an actual rights review/agreement covers automated retrieval, your intended
use, and how you return that data to clients. An operator reference records your
review; setting it does not grant rights. No solunar responses are cached or
persisted. Optional providers have no enable switch: access/product/licensing
review and adapter implementation must precede activation.

## Connect with stdio

```powershell
.venv\Scripts\python -m weather_fishing --transport stdio
```

The MCP client normally starts this process. Example configuration (replace paths
with your checkout; schemas are discoverable through `tools/list`):

```json
{
  "mcpServers": {
    "weather-fishing": {
      "command": "C:/Projects/CommonTools/weather-fishing-mcp/.venv/Scripts/python.exe",
      "args": ["-m", "weather_fishing", "--transport", "stdio"],
      "cwd": "C:/Projects/CommonTools/weather-fishing-mcp",
      "env": {"WF_USER_AGENT": "YourFishingApp/1.0 (your-contact)"}
    }
  }
}
```

`cwd` is client-specific. If your client does not support it, use an absolute
path to the installed `weather-fishing-mcp` executable and supply settings through
the client process environment. Stdio relies on process/OS access controls.

## Connect with authenticated HTTP

Generate an HTTP bearer secret and provide it to both server and trusted client:

```powershell
$env:WF_API_KEY = (.venv\Scripts\python -c "import secrets; print(secrets.token_urlsafe(32))")
.venv\Scripts\python -m weather_fishing --transport http --port 8010
```

MCP URL: `http://127.0.0.1:8010/mcp/` (trailing slash avoids a mount redirect).
Configure the client's `Authorization: Bearer <WF_API_KEY>` header. Startup fails
for secrets shorter than 32 characters. `/health` reports process liveness, not
live-provider readiness. All other routes require authentication. DNS rebinding
protection permits localhost hosts/origins. The service binds to loopback and is
intended for local clients; remote hosting needs an explicit TLS/auth/host-policy
design. No public deployment, cloud account or credentials are created here.

## Quick tool examples

```json
{"tool":"provider_capabilities","arguments":{"provider":"nws"}}
```

```json
{
  "tool": "get_forecast",
  "arguments": {
    "location": {"latitude": 38.9, "longitude": -77.0},
    "timezone": "America/New_York",
    "units": "metric",
    "fields": ["temperature", "windSpeed", "probabilityOfPrecipitation"],
    "limit": 12
  }
}
```

```json
{
  "tool": "get_tides_currents",
  "arguments": {
    "location": {"station_id": "8443970"},
    "start_date": "2025-04-01",
    "end_date": "2025-04-02",
    "timezone": "America/New_York",
    "units": "metric",
    "product": "predictions",
    "datum": "MLLW"
  }
}
```

These are calls, not fixture data. The full examples cover all 11 tools in
[the tool reference](docs/tools.md).

## Context and output bounds

Tool results contain a compact `structuredContent` object plus a short text status,
so JSON is not duplicated in two model-visible channels. Use an MCP client that
supports structured tool results. Text-only legacy clients will see just the status.
This is ordinary MCP structured output, not an HTTP endpoint returning bare JSON.

Each data tool defaults to 100 records (maximum 500), supports `fields`, and limits
its serialized result to roughly 60 KB plus a small truncation explanation. Paging
drops whole records and returns `next_offset`; a single oversized record returns
unavailable and asks for fewer fields. A bundle accepts at most eight data requests.
Forecast/grid variables and scientific quantities are not invented or interpolated
to make a compact answer.

## Operation and retention

Settings use `WF_` environment variables, optionally read from a local ignored
`.env`. Secrets are Pydantic secret values and are never logged. Requests use fixed
provider HTTPS origins, no caller URL, no redirects, no environment proxy, bounded
streamed bytes, and finite timeouts. Provider failures remain separate from siblings.

One process owns provider request pacing and the RAM response cache. Ordinary
providers are paced at one request/second. Upstream `Retry-After` cooldowns are
respected; long waits return unavailable instead of retrying early. NWS failure
retries are deferred by at least 60 seconds. Other public adapters attempt at most
three GETs; Solunar makes one attempt. See [architecture](docs/architecture.md).

Responses are never persisted. The RAM cache respects `no-store`, `no-cache`,
`private`, `max-age`, `Age` and `Expires`, subject to shorter local provider caps.
Cache hits preserve upstream `retrieved_at`; `served_at` is the current call time.
The cache is limited to 48 entries/20 MB by default, with a 5 MB upstream body limit.
Solunar has no response cache. SQLite stores only hashed NCEI token identifiers,
UTC days and attempt counts, deleting rows older than two days. It conservatively
budgets 9000 attempts across the current and previous UTC dates, conservatively
bounding any rolling 24-hour window because the documented daily reset timezone
is unspecified. Other applications sharing the token still need coordination.
Run a single worker.

## Tests and live verification

```powershell
.venv\Scripts\python -m pytest -q
.venv\Scripts\ruff check src tests scripts
.venv\Scripts\ruff format --check src tests scripts
.venv\Scripts\python -m build
```

Tests use explicitly synthetic provider fixtures, mocked outages, actual local
HTTP transport and the official MCP stdio/HTTP clients. They do not prove public
access. Opt-in live checks make public requests and record metadata separately:

```powershell
.venv\Scripts\python scripts/live_check.py
# Inspect exactly one April 2025 public Solunar table for availability/parser QA.
# This does not enable production access or establish commercial rights.
.venv\Scripts\python scripts/live_check.py --inspect-solunar
```

Results go to ignored `verification/live-check.json`; neither failures nor missing
credentials trigger fixture substitution. Provider terms can change: review the
linked sources and any actual agreements before scaling or redistributing data.
