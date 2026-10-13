# Resolution, collection and model handoff

CommonTools owns geographic resolution, timezone lookup, station/product qualification,
retrieval, normalization and provenance. Fishing AI submits requests, handles returned
clarifications, validates the package and persists permitted snapshots. This change adds
no retrieval tooling to Fishing AI, no model client and no deployment.

## Tool workflow and contracts

The original 11 tools remain available, including the request-list `collect_conditions`.
Three new tools expose strict Pydantic input/output schemas through `tools/list`:

| Tool | Input | Output |
| --- | --- | --- |
| `resolve_location` | Exactly one of `place` or `coordinates`; optional country, region, waterbody, candidate_id | `ResolutionResult` v1.0: status, state, context, candidates, reasons, missing_fields |
| `resolve_station_product` | Returned context, provider, product, inclusive local start/end dates, datum, optional bin/station_id/discovery offset | StationSelection: qualified/unverified/clarification relevance, metadata qualification status, station, candidates, provenance, limitations, reasons, next_offset |
| `collect_resolved_conditions` | Returned context, local window, permitted_providers, optional units/tide_product/datum/current_product/current_bin/offsets/limits | `ConditionsPackage` v1.0: context, local and UTC window, independent categories, source evidence, records, statuses and continuations |

Use the schemas for exact field types. Never supply station coordinates as the locality
point. A returned context distinguishes `locality_representative` from
`submitted_fishing_point`; the latter preserves the submitted coordinates even if the
reverse lookup's locality point differs. A submitted coordinate's positional accuracy
is unverified. Provider coordinate precision and optional west/south/east/north bounds
are retained; absent bounds are null. NWS relative locality is a nearby representative
locality, not an address/administrative-boundary determination. Its US jurisdiction label
comes from the provider's coverage, not a separate country-boundary lookup.

Ambiguous forward results return candidates and `clarification_required`, without a
chosen context. Repeat the original query with a returned `candidate_id`, or refine
the country/region. Even the top-ranked geocoder result must not hide alternatives.
More than ten results requires refinement. Empty/default/mismatched resolutions do
not generate coordinates. Submitted coordinates survive a lookup failure as a partial
context, with canonical locality/timezone missing. Collection requires a resolved zone.

The context includes an integrity `receipt` computed in CommonTools. Pass the context
unchanged to selection/collection. This prevents a model from editing coordinates or
timezone between stages. Receipts expire on server restart; re-resolve then. Receipts
are not authentication, geographic accuracy guarantees or persistent snapshot IDs.

```json
{"tool":"resolve_location","arguments":{"coordinates":{"latitude":42.35,"longitude":-71.05}}}
```

```json
{"tool":"resolve_location","arguments":{"place":"Springfield","country":"US","region":"VA","waterbody":"specified river"}}
```

The second example currently returns `dependency_required` in the stock server.
Global forward geocoding/timezone integration has **not been selected or configured**.
The existing NWS points adapter provides coordinate-to-relative-locality/timezone
resolution in its coverage. It does not implement place search or global resolution.
No new public geocoding endpoint is silently enabled.

After resolution, copy the actual returned context rather than replacing the following
placeholder with model-generated fields:

```json
{
  "tool":"collect_resolved_conditions",
  "arguments":{
    "context":"<the returned context object, unchanged>",
    "window":{"local_date":"2026-10-14","start_time":"22:00","end_time":"02:00"},
    "permitted_providers":["nws","coops","ndbc","ncei","solunar"],
    "limit_per_category":24,
    "max_output_bytes":60000
  }
}
```

The context string above is an explanatory placeholder, not valid executable arguments.
[Executable synthetic contract examples](examples/resolution-contract.json) show the
complete shapes, explicitly labeled as fixtures. Their receipts are intentionally not
usable production contexts. They are never loaded by production code.

## Remaining geographic integration dependency

Recommend a paid **Geoapify Forward/Reverse Geocoding** integration using the existing
Python HTTP adapter pattern. Its documented responses include locality components,
coordinates, bounds, datasource attribution and IANA timezone names, and its platform
supports commercial applications with plan/attribution constraints. This fits the
existing fixed-origin GET transport and global requirements without public Nominatim
or a model-based geocoder. See [forward API](https://apidocs.geoapify.com/docs/geocoding/),
[reverse API](https://apidocs.geoapify.com/docs/geocoding/reverse-geocoding/), and
[commercial plans and attribution](https://www.geoapify.com/).

Selection is a recommendation, **not activation**. Before implementation: choose the
actual plan/processing region, supply a restricted key, review attribution and snapshot
storage/redistribution terms for Fishing AI, establish rate/cache limits, implement a
fixed-origin credential-safe adapter, and verify ambiguous names, islands/coasts,
timezone boundaries and reverse lookup precision. An administrative bounds rectangle
does not prove waterbody identity or point timezone. Use the provider timezone for
the submitted point; use ZoneInfo date rules, not current offset fields, for DST.

`GeographyProvider` in `resolution.py` is the explicit adapter port. A CommonTools
embedding can pass `Service(..., geography=adapter)`; the adapter must return validated
`GeographicCandidate` objects with source provenance. `search` must return alternatives;
`reverse` must return a timezone applicable to the submitted coordinates. The stock
stdio/HTTP entrypoint supplies only `NWSCoordinateGeography`. There is currently no
Geoapify API key setting, active Geoapify adapter or claimed live global verification.

## Reviewed tide/current relationships

CO-OPS discovery is reused with its product-specific catalogue types. Distance ranks
stations **after** area/waterbody relevance is qualified. Names, nearest distance and
an unchecked waterbody hint are insufficient. Configure
`WF_STATION_RELATIONSHIPS_FILE` with an operator-reviewed JSON array conforming to
`StationRelationship`: canonical locality ID, actual station ID, canonical waterbody
and reviewed aliases, eligible products/date bounds, provenance and limitations.
No default relationships are shipped. The file is at most 1 MB/1000 relationships.

For a locality point, an explicit `default_for_locality=true` relationship can establish
representative area relevance without further waterbody input. Defaults covering
different waterbodies require clarification. For submitted fishing points, a reviewed
`area_polygon` must also contain the point; sharing a nearby locality ID is insufficient.
Polygons have 3–256 vertices, exclude edges conservatively and must be split across
the antimeridian. They must describe an area in which the **representative station**
is appropriate, sourced and reviewed by the operator. This is not automatic global
watershed/estuary modelling; holes/multipolygons and topology validation are unsupported.

Station catalogue membership checks provider/product support. Reviewed applicability
dates and available installation/removal metadata constrain dates; observed products
reject future dates. Selection checks datum listing and, for currents, explicit listed
bin/depth metadata. Tide predictions, observed water levels and current products remain
distinct. A current request triggers its own current catalogue/selection/bin check;
a selected tide station does not automatically establish current suitability.
Subordinate predictions require a verified reference ID and matching offset metadata;
subordinate currents also validate the reference bin. Missing optional reference type
is a limitation, not fabricated metadata. Actual product/date availability still
requires the data response; installation/catalogue dates do not prove uninterrupted
sampling. Catalogue bin depth is not historic deployment depth, and no interpolation
is performed. See [CO-OPS metadata contracts](https://api.tidesandcurrents.noaa.gov/mdapi/prod/).

No qualified relationship yields candidates/clarification. Discovery returns one page
of at most 20 candidates within 100 km and an explicit next_offset; selection is not
an exhaustive nearest-station search. A requested station ID still requires qualification
and must occur on that page. Call `resolve_station_product` with its next_offset to
inspect further candidates. The higher collector does not silently crawl all pages.
Other categories continue regardless of unknown waterbody context; it never becomes
`not_applicable` by default.

## Collection semantics and limits

| Category | Deterministic product plan |
| --- | --- |
| weather | Past local dates: NCEI GHCND station observations (TMAX/TMIN/PRCP); current/future: NWS hourly forecast |
| marine | Past dates: NDBC standard met archive (WTMP/WVHT/DPD/WSPD); current/future: NWS grid variables |
| tides | CO-OPS predictions by default; explicitly requested water_level/hourly_height stay observations |
| sun_moon | Exact reviewed SolunarForecast locality/month astronomy fields |
| solunar | Sole provider SolunarForecast; exact locality/month solunar predictions |
| currents (optional) | Independently qualified CO-OPS current observations/predictions and explicit bin |

Only permitted providers are called. No provider substitution occurs on failure.
Mixed past/future windows retain separate product envelopes within a category. NCEI
stations must cover requested dates in their metadata; nearest distance remains a
representative choice. NDBC archive deployment relevance remains unverified. Existing
NWS recent observations remain available as a low-level tool, but the high-level
collector does not misrepresent them as a general historical archive. This plan is
not worldwide weather coverage; other provider adapters remain unimplemented.

`WF_SOLUNAR_LOCALITIES_FILE` is a reviewed canonical-locality-to-exact-slug array of
`SolunarLocality` records, with provenance and optional operator-verified source timezone.
Display names are never converted into guessed slugs. No mapping is shipped. The
existing access gate, runtime country/state/city/month checks and April 2025 lower
bound apply unchanged. A cross-month window issues separate monthly requests, retaining
successful months when another fails. `sun_moon` and `solunar` are independently
reported. Both call the same monthly source; Solunar response caching remains disabled.
No alternate astronomy or solunar provider is synthesized.

Dates are local inclusive dates translated to a half-open UTC window. A clock end
earlier/equal to its start crosses midnight when no explicit end_date is supplied.
DST days may contain 23 or 25 hours; ambiguous clock endpoints require explicit
start_fold/end_fold, nonexistent endpoints fail validation. Calendar-labelled daily
rows are retained with a limitation for subdaily windows, not treated as timed samples.
Interval records are retained as intervals, never joined into synthetic measurements.

Each category has separate relevance_status, retrieval_status and coverage_status.
`complete` retrieval means the returned requested page has no identified omissions,
not complete local/window coverage. Coverage remains unverified unless an identified
gap is reported. Missing fields (including null quantitative objects), source warnings,
empty pages, access gates, failed requests and continuations stay visible. A qualified
station can have unavailable retrieval. A provider outage never loads a fixture.

The package itself is the deterministic factual snapshot: no model-written facts are
merged into it. Records carry source_time/source_end_time, values, optional source_values
for transformed/parsed raw data, source_units, source_url and code-assigned evidence_refs.
NWS quantities already preserved unchanged in values are not copied into a second raw
value object. CO-OPS numeric source strings, NDBC tokens/sentinels/source units, NCEI
attributes and Solunar text/clocks survive normalization. NDBC archive records link
to their own file, rather than whichever archive was retrieved first. Evidence entries
contain actual data/metadata URLs, retrieval time when known and exact tool arguments;
unknown metadata retrieval times remain null. Units/datum belong to product envelopes;
there is no invented common height datum or unit conversion for unsupported quantities.

One page is retrieved per planned data request (up to 100 records; default 24).
No hidden pagination loop exists. `continuations` return exact low-level tool arguments
and request_key values. Follow them explicitly, or repeat collection with offsets such
as `{"weather:0":24}`. The category shortcut `weather` applies to every weather part;
use request keys for mixed products/months. Provider indices survive clock filtering and
aggregate truncation, so dropped rows are not skipped. Provider upstream truncation
without an offset remains a gap requiring a narrower request. Future re-fetches may
change live source pages; offsets are not stable archival cursors.

Aggregate UTF-8 JSON is bounded to max_output_bytes (16–120 KB, default 60 KB), including
context, evidence, raw values and metadata. Whole records are removed with continuations;
values are never shortened to fit. Unrepresentable metadata returns an explicit
aggregate_metadata_too_large result. The compatible request-list bundle is bounded
to 120 KB as well. Each low-level result retains its existing ~60 KB limit. Resolution
and selection have a 120 KB metadata ceiling. Collection planning has finite provider
calls and a deadline of five times WF_TOOL_TIMEOUT (default 250 seconds); individual
provider/tools retain their existing bounded deadlines. Clients should allow this
workflow deadline. Cancellation at the outer deadline returns tool-level unavailability;
no background retrieval continues after cancellation.

## Model handoff

MCP tool availability, discovery and a functioning **client tool loop** are prerequisites.
The client must execute requested tools and pass the returned package to the model.
A plain chat-completions request does not execute MCP tools. Fishing AI should validate
schema_version, statuses, receipt during the live workflow, evidence links, dates,
units and datum, then persist the permitted snapshot itself. Persisted packages do not
need an active receipt to be explained; they must not be reused for collection after
restart. Snapshot retention must follow each provider's applicable rights.

Short example explanation prompt after the client has assembled and validated the package:

> Explain this validated conditions package for the requested fishing window. Cite its
> evidence references. Report category gaps and representative-station limits. Keep
> predictions distinct from observations and interpretation clearly labeled. Use only
> returned facts; do not fill missing measurements, locations, IDs or events.

WF_TEXT_RESULTS=true returns **one** bounded JSON text block equal to structuredContent
for LM Studio/text-only model hosts. WF_TEXT_RESULTS=false returns compact status text
plus structuredContent. There is no second status+JSON text copy. Clients exposing both
channels should ingest one copy. SDK channel tests do not prove a particular LM Studio
model follows the prompt. This implementation does not promise automatic JSON-page
reading or form-button PDF downloads; neither is implemented/verified here.
