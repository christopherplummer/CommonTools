# Validation record

## Resolution and collection layer — October 13, 2026

The new layer and its remaining geographic/station-policy dependencies are documented
in [the implementation/contract guide](resolution-collection.md). Existing validation
below is retained as historical evidence; it does not independently verify this layer.

| Final check for this change | Actually observed |
| --- | --- |
| Full pytest suite | **108 passed**, 16.70 seconds |
| Ruff lint / format | Passed; 30 Python files formatted |
| `pip check` | No broken requirements |
| Source archive and wheel | Built successfully with pinned Hatchling |
| Local SDK stdio / authenticated HTTP | 14 discovered schemas; configured unit defaults; higher-level JSON text equals structuredContent; successful synthetic weather package records have evidence refs |
| Synthetic contract JSON | Validated against the actual input/output Pydantic models |

All deterministic provider/geographic samples, relationship polygons, outages and
contract outputs are explicitly **synthetic**. New coverage includes locality
ambiguity, submitted/locality/station point identity, context tampering/restart,
different nearby waterbodies, reviewed area defaults and polygon exclusion,
unsupported products/date bounds/datums/current bins, subordinate reference checks,
DST 23/25-hour days, ambiguous/nonexistent endpoints, cross-midnight/month windows,
partial monthly failures, null measurements, NCEI upstream paging, source evidence,
aggregate record continuation indices and both collector/bundle byte bounds.
These tests verify code behavior, not global geographic data, real watershed relevance,
credentialed NCEI availability or Solunar commercial access. MCP checks use actual
local SDK clients/servers with synthetic upstream data; no LM Studio UI/model was run.

The final live pass started at **12:27 p.m. Eastern** (16:27 UTC) on October 13, 2026.
See [actual machine-readable metadata](resolution-live-verification.json);
fixture_data_used is false. `scripts/live_resolution_check.py` uses the desktop
stdio launcher and SDK, with actual public NOAA retrieval:

| Request | Actually observed | Limits |
| --- | --- | --- |
| Resolve submitted 42.35,-71.05 | NWS returned Boston/MA, America/New_York and distinct relative-locality point 42.3385513,-71.018253 | NWS relative locality, not exact address/bounds; global forward search unconfigured |
| Collect October 14 local date | Weather: 3 hourly records; marine: 3 independent grid intervals; all records had evidence refs | Partial pages, marine source units, no assertion of full window coverage |
| Tide selection during collection | 20 actual candidates; clarification required; no station selected/retrieved | No reviewed waterbody/area relationship was supplied; distance was not used as proof |
| sun_moon / solunar | Both unavailable under the existing license_review_required gate | No gated provider call, fixture fallback or global history claim |
| Existing explicit Boston tide tool | 3 actual April 1, 2025 predictions, MLLW, source raw strings retained | Partial page; caller-selected station does not prove automatic local suitability |
| Model-visible SDK result channel | Text JSON matched structuredContent for resolution, collection and explicit tide request; collection JSON was 18,504 UTF-8 bytes | Verifies SDK/model-visible channel, not LM Studio itself or model explanation quality |

No live qualified automatic station selection was claimed: reviewed relationship
catalogues are not shipped. No live global forward geocoder/timezone integration,
new credentialed NCEI run, licensed Solunar collection or subordinate-current reference
workflow was performed for this change. Those cases are contract/fixture verified
where implemented, with the configuration/access dependencies reported explicitly.
Geoapify is a documented concrete recommendation, not an installed/enabled provider.

The default filesystem sandbox blocked pytest temporary-file operations and some
Python subprocess runs. Successful test/build/live runs used reviewed filesystem
and network access. Failed attempts were not counted as successful verification.
No changes to Fishing AI, public deployment, push or live fixture substitution occurred.

Completed October 13, 2026 on Windows with Python 3.12.10. Tests, actual public
requests and unresolved access requirements are recorded separately. No fixture
replaced a missing credential, failed live request or unsupported provider product.

## Deterministic tests and package checks

An isolated project `.venv` was created and the declared runtime/dev dependencies
installed. Their actual resolved versions are saved in `requirements.lock`.

| Check | Observed result |
| --- | --- |
| Pytest | **58 passed**, 8.24 seconds |
| Ruff lint | All checks passed |
| Ruff formatting | All 22 Python files already formatted |
| `pip check` | No broken requirements |
| Source archive and wheel | Built with the pinned Hatchling backend |
| Official MCP SDK stdio client | Initialize, discover 11 tools with input/output schemas, inspect structured result |
| Official MCP SDK HTTP client | Local server initialize/call, bearer authentication and unauthenticated rejection |

Tests cover synthetic provider formats, station/zone identity, unsupported global
coverage, prediction versus observation/archive kinds, datum preservation, DST
conversion/ambiguity, midnight overlap, null/sentinel fields, source-day labels,
Solunar missing days/default city/month/highlighted values, independent bundled
failures, disabled providers, no fallback, byte paging, compressed archive bounds,
fixed origins/redirect rejection, cache directives, cooldowns, bounded retries and
credential-free persistent quota accounting across a day boundary.

Tests are explicitly synthetic fixtures in `tests/`, and mock failures are labeled
synthetic. Production modules do not import them. MCP transport checks exercise a
real local server/client but do not establish public provider access.

The filesystem sandbox denied Python temporary-directory operations for the first
test/build attempts. Successful tests and builds ran with reviewed filesystem
permission. Public network checks also required reviewed network access. These were
environment restrictions, not substituted successes. The commands can normally run
without these Codex sandbox restrictions in a user's own Python environment.

## Public provider checks actually performed

The final live pass ran on October 13, 2026 at approximately **8:36 a.m. Eastern**
(12:36 UTC). Exact per-request times, source URLs, statuses, counts, missing fields
and reasons are in [the machine-readable live record](live-verification.json).
Responses were inspected/parsed but provider data bodies were not saved in that
record. Its `fixture_data_used` is false.

| Integration | Observed request/result | Scope of verification |
| --- | --- | --- |
| NWS point/station discovery | Washington DC coordinates; five returned stations, more available | Actual point mapping/station parse and paging |
| NWS weather forecast | DC forecast, SI units; three selected periods | Actual forecast retrieval/normalization, short output page |
| NWS alerts | DC active alerts returned zero records | Actual successful empty alert query; does not verify an active hazard's contents |
| NWS observations | KDCA recent temperature/wind; two records | Actual station identity and quantity/QC objects; upstream page incomplete |
| NWS marine zone | ANZ230 forecast; two text periods | Verified coastal marine zone and text parse |
| NWS marine grid | 42.25,-70.6; waveHeight/windSpeed intervals | Actual coastal grid wave/wind variables and source units |
| CO-OPS station discovery | Boston coordinates; three stations | Actual metadata network query/paging; some optional station metadata absent |
| CO-OPS tide predictions | Boston 8443970, April 1–2, 2025, MLLW/GMT/metric; seven events | Actual past-dated predictions; not archived issued forecasts |
| CO-OPS water-level history | Boston hourly_height, April 1, 2025; three records | Actual historical observations; absent optional quality field reported |
| CO-OPS current predictions | EPT0003 bin 14, April 1, 2025, ten-minute speed/direction | Actual current prediction response and catalogue bin validation |
| CO-OPS current observations | cb0102 bin 1, October 13, 2026 | **Unavailable**: provider returned no data for this product/time |
| CO-OPS historic currents | CFR1624 bin 9, April 1, 2016; three records | Actual historical current observations, not substituted realtime |
| NDBC discovery/realtime | Active catalogue and buoy 41009 standard met | Actual XML/text parse; response gaps/nulls retained |
| NDBC annual history | 41009h2025 compressed archive, April 1 filter | Actual archive decompression/UTC dates/sentinels; missing water/wave values reported |
| NOAA Fisheries species | Atlantic cod biology field | Actual official profile excerpt, marine/regulatory qualifications retained |
| NOAA Fisheries directory | Three links from landing page | Actual directory links, not exhaustive catalogue proof |
| NCEI CDO history | Intended Boston GHCND query | **Not run**: no user token configured; fixture tests only |
| SolunarForecast public monthly inspection | Beverly Hills, California, US, April 2025; 30 dates, no missing fields/dates | Actual location/month/parser availability, **not** licensed production use or source-zone verification |

Partial live responses mostly reflect deliberately small output limits. Some also
contain missing measurements or provider pagination, as recorded. A nonempty record
list is not proof that all requested measurements exist or that worldwide coverage
is continuous. The current-observation failure remains in the record even though
a separate historical current station worked.

## Outstanding requirements and limits

- NCEI: obtain a token, review actual dataset/source rights, then perform live
  station/discovery/date/unit/pagination checks; no credentialed call was verified.
- SolunarForecast: establish automated-access/use/redistribution rights before
  enabling production. Verify each selected city's source IANA timezone separately.
  April 2025 availability was verified only for Beverly Hills, and no exhaustive
  history crawl or global availability claim was made.
- Met Office/BOM/Tides4Fishing/timeanddate: catalogue plans only, no adapters or
  access credentials. Specific product/interface, rates, licenses, attribution,
  retention and commercial requirements remain to be resolved and implemented.
- NDBC retired-station metadata and non-standard files are unsupported; active
  catalogue positions do not prove historical deployment positions. Current-year
  archive URL layout is fixture/documentation covered but was not live checked.
- CDO datatype units beyond the explicit common temperature/precipitation mappings
  retain qualifications. Marine text/grid and recent NWS quantities remain in source
  units. No general geocoder, archived forecast service, regulatory verification,
  species occurrence predictor or fish-activity observation service exists here.
- No remote hosting, TLS termination, public exposure, production load test or
  multi-user deployment was performed. The setup is loopback HTTP or client-spawned
  stdio with a single process. Provider access/terms may change after this record.

See [provider source/access review](providers.md) for current source links and the
distinction between published provider requirements and conservative local policy.

## LM Studio setup follow-up

Added `scripts/run_stdio.py` and [LM Studio setup instructions](lm-studio.md).
The launcher was checked with the official MCP SDK from a different initial working
directory: initialization succeeded, all 11 tools were discovered, and a structured
NWS capability response was returned. The launcher sets the project directory so
local `.env` settings and relative quota storage resolve consistently.
LM Studio itself and a particular local model have not been exercised end to end;
in particular, model-visible handling of `structuredContent` remains to be checked.

## LM Studio text-result compatibility correction

The user subsequently reported that LM Studio's model saw only the short status
text and missed the forecast JSON in `structuredContent`. Added `WF_TEXT_RESULTS`
and enabled it by default in the desktop launcher. This sends the same bounded JSON
in text content while retaining the structured result required by the tool schema.
Generic server startup keeps compact structured mode by default; client environment
`WF_TEXT_RESULTS=false` explicitly opts out of desktop compatibility mode.

The exact reported DC forecast query was rechecked through the stdio desktop
launcher against live NWS data on October 13, 2026 at 9:55 a.m. Eastern. Text JSON
equaled `structuredContent`, contained three temperature/windSpeed records, and was
1750 UTF-8 bytes. The sole partial reason was output pagination, with `next_offset=3`.
No fixture supplied these records. See [compatibility check metadata](lm-studio-compat-verification.json).
The LM Studio application itself was not automated; its prior failure was reported
by the user, and the corrected model-visible channel was verified with the SDK.

The expanded suite passes **60 tests** (10.84 seconds), including desktop launcher
compatibility/opt-out, unavailable-result text, and actual local HTTP forecast JSON
with pagination. Ruff lint and formatting also pass. Restart the running MCP server
after this change; already-loaded processes retain the previous code.

## Configurable unit-preference follow-up

Added validated `WF_DEFAULT_UNITS` (`metric`, `imperial`, `source`; default `metric`).
Individual tools and bundled calls inherit it when `units` is omitted. Explicit
arguments override it. Tool discovery advertises the configured default and startup
instructions explain the preference. No additional conversions were added for
source-only quantities.

The expanded suite passes **77 tests** (15.91 seconds). Preference tests cover
environment validation, all three MCP schema defaults through actual stdio clients,
weather/tide/NCEI request units, buoy numeric conversion, explicit overrides within
bundles, invalid explicit units and preservation of caller arguments. Ruff lint and
formatting pass for all 24 Python files.

A separate actual public request used the desktop launcher with
`WF_DEFAULT_UNITS=imperial` and a three-call bundle for Ruskin on October 16, 2026:
NWS returned Fahrenheit/mph, the Little Manatee River tide request returned feet,
and an explicit metric override returned meters. Both tide requests contained the
same two event timestamps and heights agreed after feet-to-meters conversion within
0.005 m. Weather was partial solely because the request limited output to two
forecast periods; both tide responses were complete. No fixture supplied this live
data. Text JSON matched the structured result, and discovery advertised imperial.
This verifies the launcher/protocol path; the LM Studio UI/model was not automated.
