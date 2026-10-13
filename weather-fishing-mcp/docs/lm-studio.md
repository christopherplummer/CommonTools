# LM Studio installation

Use the local stdio server. LM Studio starts the Python process; no separate web
server, Docker container or HTTP bearer key is needed for this connection.
The project `.venv` is already installed on this machine.

## Connect this checkout

In LM Studio open **Program → Install → Edit mcp.json**. Add the
`weather-fishing` entry to the existing `mcpServers` object, keeping your other
servers. If the file is empty, the complete configuration is:

```json
{
  "mcpServers": {
    "weather-fishing": {
      "command": "C:/Projects/CommonTools/weather-fishing-mcp/.venv/Scripts/python.exe",
      "args": ["C:/Projects/CommonTools/weather-fishing-mcp/scripts/run_stdio.py"],
      "env": {
        "WF_USER_AGENT": "CommonTools-Fishing/0.1 (replace-with-your-contact)",
        "WF_DEFAULT_UNITS": "imperial"
      }
    }
  }
}
```

Replace the User-Agent contact with your application's contact information. The
launcher sets the working directory to this project, so a local `.env` and the
relative quota database path work even if the host's launch directory is different.
Use these paths only for this machine/checkout; adjust them on another computer.

`WF_DEFAULT_UNITS` selects your preferred unit system: `metric`, `imperial`, or
`source`. The server uses `metric` if the setting is absent. Calls without `units`
inherit this preference; explicit per-call units still win, including within a
bundled snapshot. Tool discovery shows the configured default. Reload/restart the
server after changing it. Remove explicit metric instructions from older prompts
when you want them to follow the preference.

Imperial preferences request Fahrenheit/mph for NWS period forecasts, feet for
CO-OPS heights and knots for CO-OPS currents/NDBC winds where supported. Marine
text/grid and source-only scientific fields keep their labeled source units.

Save the file. LM Studio's documentation says it automatically loads configured
servers after saving. Confirm that weather-fishing is connected and its 11 tools
are listed/enabled in your chat. Load a model capable of tool use and try:

> Use weather-fishing's provider_capabilities tool to show the enabled providers.

Then try a compact actual data query:

> Use get_forecast for latitude 38.9, longitude -77.0. Return the next three periods
> with temperature and windSpeed, America/New_York timezone. Omit the units argument
> so the server uses my configured default unit preference. Include the returned units.

The server process, discovery and result schema were checked with the official MCP
SDK. That is not an end-to-end verification of LM Studio or your selected model.
The launcher enables `WF_TEXT_RESULTS=true`, so the bounded JSON is present in text
content as well as `structuredContent`. This addresses the reported LM Studio
behavior in which the model received only the short status text. An existing server
entry using this launcher only needs a restart/reload after this update. If your
entry starts the module directly, add `"WF_TEXT_RESULTS": "true"` to its `env`.
An explicit `WF_TEXT_RESULTS=false` in the client environment disables this mode
for hosts that expose structured results properly. Partial results include both
actual records and reasons; a short output page is not a provider access failure.

## Configure the optional credentials and review records

Copy `.env.example` to `.env` in the project directory only if `.env` does not
already exist. Edit it locally; do not send keys in chat. Environment values in
LM Studio's entry take precedence over the same keys in `.env`.

- `WF_NCEI_TOKEN`: your actual CDO token. The adapter is implemented but was not
  credentialed/live tested. Get the token through NOAA's email registration flow,
  then restart/reload this MCP server and run the live check for NCEI.
- `WF_SOLUNAR_PERMISSION_REFERENCE`: a reference to an actual rights review or
  permission covering your use. The application gate was added because the site's
  published terms permit personal noncommercial use and restrict redistribution.
  Merely entering a value does not establish that automated retrieval or your use
  is permitted. Leave it blank until that is resolved. Astronomy from the same
  provider is also gated. Verified source-city IANA timezone is a separate tool
  argument; without it, source clock strings are retained and output is partial.
- The four optional providers have no functioning adapter or enable switch. Keys
  alone cannot activate Met Office, BOM, Tides4Fishing or timeanddate. Access/terms
  review, code and testing are still required. Tides4Fishing remains tides only.

## Troubleshooting and limits

For the higher-level workflow, see [resolution, collection and the short explanation
prompt](resolution-collection.md#model-handoff). A functioning client MCP tool loop
must execute resolution/collection and supply the validated package. A plain
chat-completions request does not execute these tools. SDK transport/text checks are
separate from verification of LM Studio itself or any particular model.

If the server cannot start, confirm both configured paths exist and that the
project was installed in its `.venv`. On a fresh checkout use the setup commands
in [README](../README.md). On this machine you can verify the import with:

```powershell
& C:\Projects\CommonTools\weather-fishing-mcp\.venv\Scripts\python.exe -c "import weather_fishing; print(weather_fishing.__version__)"
```

The launcher normally waits for MCP input; an apparently idle terminal is not
proof of a startup failure. Use LM Studio's MCP connection/logs to diagnose it.
For low context use, select fields and small limits; avoid requesting the entire
capability catalogue or hundreds of hourly records unnecessarily.

If you see the old “Use structuredContent” status instead of JSON after this update,
the host is still running an older process or compatibility mode is explicitly off.
Restart/reload weather-fishing (or restart LM Studio) and check its environment.

Local NWS/CO-OPS/NDBC/Fisheries retrieval can work while NCEI/Solunar remain gated.
The release does not cover every global location, retired NDBC station, freshwater
species, verified fishing regulations or archived issued forecasts. April 2025
Solunar availability was verified for Beverly Hills only. No public remote service
has been deployed, and a failed provider request is not replaced with fixtures.

See [coverage/access review](providers.md) and [live validation](validation.md).

Primary installation source: [LM Studio MCP documentation](https://lmstudio.ai/docs/app/mcp).
Automatic loading and Windows config location:
[LM Studio's MCP introduction](https://lmstudio.ai/blog/lmstudio-v0.3.17).
