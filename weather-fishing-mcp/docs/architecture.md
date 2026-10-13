# Architecture

`models.py` defines strict Pydantic inputs, shared result provenance, records and
bundle output. `service.py` registers the 11 tools, validates arguments, gates
provider/product combinations, isolates failures and bounds execution/output.
`server.py` publishes the same registry over the official MCP SDK's stdio and
Streamable HTTP transports; HTTP adds bearer authentication and host protection.

Each module under `adapters/` implements one provider. It never selects another
provider on failure. `http.py` owns fixed-origin GETs, response bounds, timeouts,
cooldowns, RAM cache and persisted NCEI attempt budgets. It rejects redirects
entirely; a provider endpoint change is reported for review rather than following
an arbitrary new origin. `catalog.py` exposes the integration plan and unresolved
terms as machine-readable capability records.

There is no arbitrary URL fetch, geocoder, model client, browser session, fixture
loader, file execution tool, persistent forecast archive or regulatory engine.
External text is data. Profile text and dates are normalized, with provenance and
qualifications. NOAA/NDBC source quality flags and absent values remain visible.

## Time and spatial relevance

Tool date ranges are inclusive dates in the requested IANA timezone, translated
to UTC instants for timestamped upstream products. CO-OPS always receives `gmt`,
preserving the source setting separately from output timezone. Tide datum is a
distinct result property; it is never inferred or changed by unit conversion.
Currents require an explicit bin; catalogue bin depth is labeled separately from
deployment-specific depth, which may change over time.

NCEI daily/monthly/annual date labels remain source labels with `time=null`, because
CDO's calendar dates do not provide a universal offset instant. Solunar tables also
retain source dates. Without an operator-verified source IANA zone, clock strings
are preserved and conversion is unavailable. Ambiguous/nonexistent DST local times
are not assigned fabricated offsets. A major/minor period ending earlier on the
clock than it begins is explicitly marked as crossing midnight.

NWS points and marine zones are verified with provider lookups. Stations are looked
up in provider metadata. Coordinates, when supplied, produce an actual distance
to the selected station; distances above 100 km qualify retrieval as partial.
Catalogue discovery labels candidates as representative, since proximity does not
prove same estuary, terrain, basin or current regime. No station is selected silently.
NDBC historic values retain the warning that active catalogue coordinates cannot
verify older deployments. City coordinates are not inferred from model knowledge.

## Failure and completeness semantics

`complete` means the matching available response is returned without identified
missing requested fields or truncation. It does not assert uninterrupted sampling,
universal geographic coverage, accuracy, a new live readiness guarantee or permission
to redistribute data. `partial` identifies truncation, missing fields, source-unit
limitations, unverified source clock metadata or known coverage gaps. `unavailable`
means no matching records, a gate, unsupported coverage/product or a failed request.
An empty successful active-alert response is complete with zero records.

NWS marine grid variables retain independent intervals and WMO units. They are not
joined/interpolated into fictitious hourly measurements. Past-dated tide/solunar
predictions are predictions retrieved now. None of these tools offers an archived
forecast issued in the past. Profile pages are current information, not regulation
archives. HTTP 404s, missing archives, default-city/month Solunar responses and
unrecognized response layouts never generate replacement values.

## Extension and hosting requirements

Add an independent adapter, strict input/product mapping, catalogue/source review,
fixtures and live verification notes before enabling a new provider. Prefer official
APIs when documented. The optional providers are deliberately catalogue plans only.
A flag or API key cannot activate code that has not been implemented/reviewed.

Local authentication is one trusted principal, not multi-tenant isolation. Scaling
requires shared rate coordination, token quotas and deployment security review.
Provider DNS is trusted for a small fixed set of public domains; there is no general
SSRF-safe arbitrary-origin transport. A public hosted service needs TLS, stronger
client identity/access controls, host/origin configuration and a deployment threat
model. Those changes and actual infrastructure deployment are outside this delivery.
