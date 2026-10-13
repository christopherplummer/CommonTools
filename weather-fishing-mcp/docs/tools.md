# MCP tool reference

The original 11 contracts below remain supported. The three higher-level tools
`resolve_location`, `resolve_station_product` and `collect_resolved_conditions` are
documented in [resolution and collection](resolution-collection.md), including the
versioned package, configuration dependencies and synthetic executable examples.

All tool schemas are discoverable through MCP `tools/list`. Inputs reject unknown
fields. Results use `structuredContent`; text content is a short status by default.
`WF_TEXT_RESULTS=true` includes the same bounded JSON in text for clients such as
LM Studio that may pass only text to their model. The desktop launcher defaults to
this compatibility setting. The following JSON objects show tool **arguments**, not
mocked outputs or guaranteed live data.

## Shared location, time, units and paging

Data/discovery tools take `location`: a coordinate pair, an explicit `station_id`,
an NWS `zone_id`, or country/state/city fields where supported. There is no implicit
geocoding. Discover/select a station before retrieving its observations; proximity
is only a representative match. Providing station and coordinates returns a measured
distance and qualifications. Solunar needs exact provider country/state/city slugs.

`timezone` defaults to `UTC` and must be a valid IANA name. `start_date`/`end_date`
are inclusive ISO dates; a lone start date means one day. Most timestamped products
filter using UTC bounds translated from these dates. CDO and Solunar preserve their
source calendar date labels; they are not assigned fake timestamps.

`units` is `metric`, `imperial` or `source`. Omit it to use `WF_DEFAULT_UNITS` from
the server environment/MCP entry (defaults to `metric`). An explicit argument
overrides the preference; this rule also applies to each bundled request. The
discovered schema advertises the configured default. Supported upstream conversions are
requested explicitly. Marine text/grid and recent NWS observation quantities retain
source units and say so; they return partial for unsupported conversion requests.
NDBC converts temperature, wind, wave height, visibility and tide height where
applicable, retaining source pressure/period/direction units. CDO source data may
require datatype-specific scale interpretation.

`fields` selects provider-specific values (at most 20 field names). Empty means
adapter defaults. Unknown/missing requested fields are reported. `limit` defaults
to 100 and ranges 1–500; `offset` starts at zero. Pass `next_offset` with the same
arguments to continue. Provider-page limits and the 60 KB output budget can make
a response partial. Mutable live data can change between paged calls; offsets are
not immutable archive cursors.

## Tools and examples

| Tool | Parameters beyond shared query | Providers / key qualifications |
| --- | --- | --- |
| `provider_capabilities` | Optional `provider`; no location required | All ten providers, with implementation/gate status and terms |
| `discover_locations` | `provider`, `radius_km` (default 100, max 500), `station_type`, `dataset` | NWS point stations/grid/zone metadata, CO-OPS/NDBC/NCEI stations, Fisheries directory links, exact Solunar city/month verification |
| `get_forecast` | `provider=nws`, `hourly=false`, `kind=forecast` | Latest NWS forecast; `archived_forecast` explicitly unavailable |
| `get_marine_forecast` | Same as forecast | Coordinate grid variables or explicit marine `zone_id` text; no historical text-date filtering |
| `get_alerts` | `provider=nws` | Active alerts only; no date/archive filter |
| `get_observations` | `provider=ndbc`, `historical=false`, `dataset=GHCND` | NDBC realtime or history, NCEI observations, recent NWS station observations |
| `get_tides_currents` | `provider=coops`, `product`, `datum=MLLW`, optional `interval`, explicit current `bin` | CO-OPS, at most 30 dates; `gmt` source setting; datum retained |
| `get_solunar` | `provider=solunar`, required `year`,`month`; optional verified `source_timezone` | Sole SolunarForecast source, one city/month, April 2025 or later; rights gate |
| `get_astronomy` | Same monthly/source-clock arguments as solunar | Sun/moon fields from same provider table; licensed alternate disabled |
| `get_fishing_info` | `provider=fisheries`, required official page `species` slug, optional `topic` | Current marine species excerpts; no verified regulatory coverage |
| `collect_conditions` | `requests`: 1–8 `{tool,arguments}` objects using only the eight data tools | Independent results in input order; no substitution on failures |

`discover_locations`:

```json
{"provider":"coops","location":{"latitude":42.35,"longitude":-71.05},"station_type":"tidepredictions","radius_km":50,"limit":10}
```

CO-OPS station types include `waterlevels`, `historicwl`, `currents`,
`historiccurrents`, `currentpredictions` and `tidepredictions`. NCEI discovery accepts
`GHCND`, `GSOM`, `GSOY`, optional date filters and coordinate-radius queries. Split
extent searches that cross the antimeridian. Its provider pages are not a nearest
station ranking over the whole catalogue. Solunar discovery uses the start month
if supplied, otherwise current month, and validates the exact selected city.

`get_forecast`:

```json
{"location":{"latitude":38.9,"longitude":-77.0},"hourly":true,"timezone":"America/New_York","units":"metric","fields":["temperature","windSpeed","windDirection"],"limit":24}
```

Period fields include `name`, `temperature`, `temperatureUnit`, `windSpeed`,
`windDirection`, `shortForecast`, `detailedForecast`, `probabilityOfPrecipitation`,
`relativeHumidity`, `dewpoint` and `isDaytime`. Probability/humidity/dewpoint may be
quantitative objects retaining provider units/quality metadata.

`get_marine_forecast`:

```json
{"location":{"latitude":42.25,"longitude":-70.6},"units":"source","fields":["waveHeight","wavePeriod","windSpeed"],"limit":24}
```

```json
{"location":{"zone_id":"ANZ230"},"units":"source","limit":4}
```

Grid rows return `field`, `value`, `unit` with independent validity intervals.
Fields also include `waveDirection`, `windDirection`, `windGust`, `temperature`,
`skyCover`, and `probabilityOfPrecipitation`. Empty/unavailable variables are
explicitly missing. Zone text rows use `name` and `detailedForecast`, retaining
relative period labels. Explicit zones are checked as marine/coastal/offshore.

`get_alerts`:

```json
{"location":{"latitude":38.9,"longitude":-77.0},"fields":["event","severity","headline","instruction"],"limit":10}
```

Other fields include `id`, `urgency`, `certainty`, `description`, `areaDesc`, `sent`.
An empty successful response means no matching active alerts, not unavailable data.

`get_observations`:

```json
{"provider":"ndbc","location":{"station_id":"41009"},"historical":true,"start_date":"2025-04-01","end_date":"2025-04-02","timezone":"America/New_York","fields":["WTMP","WSPD","WVHT"],"limit":100}
```

NDBC fields use official codes: `WDIR`, `WSPD`, `GST`, `WVHT`, `DPD`, `APD`, `MWD`,
`PRES`, `ATMP`, `WTMP`, `DEWP`, `VIS`, `PTDY`, `TIDE`. Availability varies by file;
realtime `MM` and historical numeric sentinels become null. History is limited to
366 dates/two calendar years; current-year archives allow three months per call.
Delayed/absent monthly files are reported rather than substituted with realtime.

```json
{"provider":"ncei","location":{"station_id":"GHCND:USW00014739"},"start_date":"2025-04-01","end_date":"2025-04-07","units":"metric","fields":["TMAX","TMIN","PRCP"],"dataset":"GHCND","limit":100}
```

Here `fields` is the upstream datatype filter; each row has `datatype`, `value`,
`attributes`, `source_date`, `station`. CDO labels remain `source_time`, with
`time=null`. GHCND allows 366 dates; monthly/annual queries are limited to 3650.
The adapter reports unsupported scales instead of inferring units for every datatype.

```json
{"provider":"nws","location":{"station_id":"KDCA"},"units":"source","fields":["temperature","windSpeed"],"limit":12}
```

NWS quantity objects preserve `unitCode`, `value`, `qualityControl`. The API's recent
history is not an exhaustive archival service. Requested dates are sent as UTC bounds.

`get_tides_currents`:

```json
{"location":{"station_id":"8443970"},"product":"predictions","start_date":"2025-04-01","timezone":"America/New_York","datum":"MLLW","units":"metric","interval":"hilo"}
```

```json
{"location":{"station_id":"CFR1624"},"product":"currents","bin":9,"start_date":"2016-04-01","units":"metric","fields":["speed","direction","bin"],"limit":10}
```

```json
{"location":{"station_id":"EPT0003"},"product":"currents_predictions","bin":14,"interval":"10","start_date":"2025-04-01","limit":10}
```

Products: `predictions`, `water_level`, `hourly_height`, `currents`,
`currents_predictions`. Tide predictions default to `hilo`. Current predictions
default to `MAX_SLACK`; other supported intervals include `h`, `6`, `10`, `30`, `60`.
Observed products use their documented default interval/product, not an arbitrary
interval override. Heights return `height`, optional `type`,`sigma`,`quality`,
`source_flags`. Currents return `speed`,`direction`,`bin` or `velocity_major` for
max/slack, plus available depth/type/flags. Catalogue depth is labeled separately;
do not assume it is the depth of a historic deployment. Source quality may be absent.

`get_solunar` (requires verified access rights before enabling):

```json
{"location":{"country":"united_states","state":"california","city":"beverly_hills"},"year":2025,"month":4,"source_timezone":"America/Los_Angeles","timezone":"UTC","limit":31}
```

Values contain `date`, `rating`, `rating_stars` (count of source icons),
`major_periods`, `minor_periods`, and available astronomy fields. Period events
retain raw clocks, converted offset instants if unambiguous/source-zone verified,
and `crosses_midnight`. Missing local rise/set events remain explicit `no_event`.
Dates/gaps refer to the source month; global historical coverage is not assumed.

`get_astronomy`:

```json
{"location":{"country":"united_states","state":"california","city":"beverly_hills"},"year":2025,"month":4,"fields":["sunrise","sunset","moonrise","moon_phase","moon_illumination_percent"],"limit":31}
```

Other fields: `moonset`, `moon_over`, `moon_under`, `day_length`. Without verified
`source_timezone`, event strings are retained and output is partial. The adapter
does not read the current-day JS offset as a historical timezone. No astronomy
calculation or alternate-provider fallback is performed.

`get_fishing_info`:

```json
{"location":{"country":"US","city":"Boston"},"species":"atlantic-cod","topic":"biology"}
```

Topics: `species` (default profile fields), `biology`, `habitat`, `management`,
`harvest`. Rows have `species`,`topic`,`text`. Text fields are capped at 4000
characters, with truncation reported. Current profiles do not support a dated
archive request. These are marine background excerpts, not verified legal rules.

`collect_conditions`:

```json
{
  "requests": [
    {"tool":"get_forecast","arguments":{"location":{"latitude":42.35,"longitude":-71.05},"fields":["windSpeed","temperature"],"limit":6}},
    {"tool":"get_tides_currents","arguments":{"location":{"station_id":"8443970"},"start_date":"2025-04-01","datum":"MLLW"}}
  ]
}
```

## Result schema

Each data result has `status`, `provider`, `kind`, `source_url`, `source_urls`,
`retrieved_at`, `served_at`, `publication_time`, `valid_from`, `valid_to`, `location`,
`station`, `timezone`, `source_timezone`, `units`, `datum`, `attribution`,
`qualifications`, `reasons`, `missing_fields`, `records`, `next_offset`, `cache_hit`.
Records have optional offset `time`,`end_time`, original `source_time`, `values`
and per-record qualifications. Records also retain source_end_time, source_values,
source_units, source_url, source_retrieved_at and evidence_refs where applicable.
Unknown publication/validity times remain null.
Available station/zone metadata URLs are retained alongside the data URL.

Kinds distinguish `observation`, `forecast`, `archived_forecast`, `prediction`,
`information`, `discovery`, `capabilities`. An unsupported archived-forecast request
still has `kind=archived_forecast` and unavailable status. A bundle has `status` and
`results`, retaining each complete provenance envelope.

Errors use explicit reason prefixes such as `credentials_missing`,
`license_review_required`, `provider_disabled`, `unsupported_coverage`,
`unsupported_product`, `not_available`, `station_mismatch`, `month_mismatch`,
`location_mismatch`, `provider_cooldown`, `rate_limited`, `tool_timeout`, or
`invalid_arguments`. No tool obtains credentials, sends messages or grants licenses.
