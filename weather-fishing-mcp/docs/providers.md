# Provider interface and access review

Reviewed **October 13, 2026** against the sources below, with separate live checks
in [validation](validation.md). This is a technical integration review, not proof
of access rights or a legal/commercial-use approval. No keys, subscriptions or
written permissions were supplied by the user. Unknown requirements remain unknown.

## Capability and coverage matrix

Global geocoding/timezone providers remain **unselected and unconfigured**. Existing
NWS point lookup resolves covered submitted coordinates only. The concrete proposed
integration and its commercial/global requirements are in
[resolution dependencies](resolution-collection.md#remaining-geographic-integration-dependency).
Operator-reviewed waterbody/station relationships are also required for automatic
qualified tide/current selection; provider catalogue distance alone is insufficient.

| Provider | Implemented products | Coverage and activation |
| --- | --- | --- |
| NWS | Latest regular/hourly forecast, marine grid/zone forecast, active alerts, recent observations, point-associated stations | US/territory coverage checked by provider; enabled |
| NOAA CO-OPS | Tide/current predictions, water-level/current observations, station metadata/discovery | CO-OPS network; enabled, station/product/range-specific |
| NOAA NCEI | CDO GHCND, GSOM, GSOY observations and station discovery | International dataset-dependent stations; token required |
| NOAA NDBC | Standard meteorological realtime and annual/monthly archives, active station discovery | NDBC/partner network; enabled; retired-station metadata unsupported |
| NOAA Fisheries | Species profile excerpts and landing-page directory links | US marine background only; enabled; not verified regulations |
| SolunarForecast.com | One country/state/city month, solunar periods/ratings and available sun/moon fields | Offered worldwide; license gate; April 2025 tested for one city |
| UK Met Office | Planned weather/marine | Disabled, adapter not implemented |
| Australian BOM | Planned weather/marine | Disabled, adapter not implemented |
| Tides4Fishing | Planned tides only | Disabled; never a solunar source/fallback |
| timeanddate | Planned licensed astronomy API | Disabled, adapter not implemented |

## NWS

[Official API documentation](https://www.weather.gov/documentation/services-web-api)
and the live [OpenAPI specification](https://api.weather.gov/openapi.json) establish
the identifying User-Agent requirement, open-data access and an unpublished numeric
rate limit. Coordinates resolve through `/points`; marine grid variables use
`forecastGridData`, while explicit marine zone forecasts retain source text.
Current endpoints are not a historical forecast service.

[Use policy](https://www.weather.gov/disclaimer) permits lawful use of federal
information with attribution and without misleading endorsement or altered content
presented as official. Third-party material has separate rights. No universal
retention duration was identified; the implementation uses RAM only, respects
upstream caching controls, caps ordinary responses at five minutes/alerts at 30
seconds, and follows the policy's minute-separated failure retry guidance.
Local one-request/second pacing is not a promised provider allowance.

## NOAA Tides & Currents (CO-OPS)

[Data API](https://api.tidesandcurrents.noaa.gov/api/prod/),
[response fields](https://api.tidesandcurrents.noaa.gov/api/prod/responseHelp.html)
and [Metadata API](https://api.tidesandcurrents.noaa.gov/mdapi/prod/) describe public
GET products, date limits, datum, bins, units and source time settings. No API key
is specified for these public interfaces; requests include an application ID.
Numeric request-rate/retention limits were not located. Local pacing is one/s;
requests are capped at 30 inclusive dates and RAM cache at six minutes.

The [NOS reuse policy](https://oceanservice.noaa.gov/about/faq.html) covers federal
information with attribution and exceptions for externally copyrighted material.
Do not infer all partner data is unrestricted. Prediction availability is verified
by station metadata plus the actual product response. Default depth selection is
not used. GMT is requested upstream and reported separately from display timezone.
Current source speed units are cm/s or knots; tide heights preserve datum.

## NOAA NCEI

[CDO v2 documentation](https://www.ncei.noaa.gov/cdo-web/webservices/v2) requires a
token and specifies five requests/second and 10000/day. The adapter uses one/s and
a persistent 9000-attempt budget across current/previous UTC dates, conservatively
covering any rolling 24 hours without assuming a reset timezone. A token shared elsewhere can
still exhaust the real provider quota. Pagination and datatype/source attributes
are preserved. The implementation restricts datasets to GHCND/GSOM/GSOY.

[Archive policy](https://www.ncei.noaa.gov/archive) distinguishes government works
from other holdings; [dataset licensing guidance](https://www.ncei.noaa.gov/erddap/legal.html)
also warns that licenses differ. The latter is not a CDO blanket license. Check the
actual dataset/source metadata and intended reuse. No CDO-wide retention term was
found: no response persistence and RAM cache at most one hour. CDO access remains
unverified without a user token. Dates are source calendar labels, not invented UTC
midnight instants; source units require dataset-specific scale review.

## NOAA NDBC

[Official HTTPS retrieval guide](https://www.ndbc.noaa.gov/faq/rt_data_access.shtml),
[measurement/units and missing-data rules](https://www.ndbc.noaa.gov/faq/measdes.shtml),
[archive guide](https://www.ndbc.noaa.gov/faq/archive.shtml) and
[archive layout](https://www.ndbc.noaa.gov/faq/dataindex.shtml) document flat files,
UTC source times, realtime missing markers, historical sentinels, annual archives
and current-year monthly files. No API key is required. NDBC asks users to minimize
polling; most stations report hourly. Local RAM caching is at most one hour and
outbound pacing one/s, not a provider quota declaration.

[NOAA policy](https://www.noaa.gov/disclaimer) and federal attribution apply;
partner station/operator restrictions may differ. No generic retention limit was
identified, so no response persistence is provided. The adapter verifies IDs in
the [active station catalogue](https://www.ndbc.noaa.gov/activestations.xml), labels
station positions as representative, and does not assume those positions prove
historical deployment relevance. Retired stations without that metadata explicitly
return unavailable. Only standard meteorological files are parsed in this release.

## NOAA Fisheries

The [official directory](https://www.fisheries.noaa.gov/species-directory) and
[species profiles](https://www.fisheries.noaa.gov/species/atlantic-cod) supply marine
biology, habitat, population, management and harvest background. No documented
generic public species-profile API was verified, so this adapter extracts identified
fields from official HTML. It does not rely on the older FishWatch API as a current
interface. Directory discovery returns only links actually present on the page.

[Fisheries website policy](https://www.fisheries.noaa.gov/national/about-us/website-policies-and-disclaimers)
distinguishes federal text from third-party copyrighted text and requests NOAA
acknowledgement. Numeric automated-access and generic retention ceilings were not
found. Local one/s pacing, short RAM caching and 4000-character field excerpts
reduce retrieval/republication volume. Local species presence, freshwater coverage,
current legal fishing permissions and regulatory limits are not verified.

## SolunarForecast.com

[Provider homepage](https://solunarforecast.com/) and
[city table](https://solunarforecast.com/solunartable-city.aspx) expose country,
state/region and city selection and adjacent-month URL paths. No documented official
automation API or numeric request limit was located. One monthly table is requested
per call, with no response caching or persistence and no bulk historical crawler.

[Terms](https://solunarforecast.com/termsofuse.aspx) restrict use to personal,
noncommercial purposes and restrict copying, redistribution and derivative use.
Production retrieval therefore defaults to `license_review_required`. Confirm
automated access, commercial/noncommercial scope, attribution, retention and
returning data to client/model users in an actual permission review before setting
the operator reference. A subscription alone is not treated as permission to
redistribute. Source labels/ratings remain provider predictions.

The [Beverly Hills April 2025 table](https://solunarforecast.com/hunting_fishing/best_times/table/united_states/california/beverly_hills/4/2025/)
was inspected live: exact city/month and all 30 dates were present. No claim is made
about other cities/months. Each runtime call checks selected options, month heading,
dates/duplicates and missing days. Responses earlier than April 2025 are rejected.
The site did not provide verified IANA timezone metadata; the current-day JavaScript
UTC offset is not reused to infer historical timezones. Without operator source-zone
verification, clocks remain source strings. Sun/moon data come from this same table;
there is no invented astronomy or solunar fallback.

## Optional provider access requirements

| Provider | Reviewed primary source | Outstanding work before any activation |
| --- | --- | --- |
| Met Office | [DataHub FAQ](https://datahub.metoffice.gov.uk/support/faqs), [terms](https://www.metoffice.gov.uk/binaries/content/assets/metofficegovuk/pdf/data/met-office-weatherdatahub-terms-and-conditions.pdf) | Pick subscribed weather/marine product, obtain key (`apikey` header), review plan quotas/retention/redistribution, include required “Powered by Met Office data” attribution, implement/test adapter |
| BOM | [Data services](https://www.bom.gov.au/resources/data-services), [copyright](https://www.bom.gov.au/other/copyright.shtml) | Some free text products exclude commercial use; select permitted subscription/interface, verify credentials, license/attribution/quotas/retention, implement/test adapter |
| Tides4Fishing | [Official site](https://tides4fishing.com/) | No official API or commercial automated-retrieval rights verified; establish all terms and permitted interface first; implement tides only |
| timeanddate | [Astronomy docs](https://dev.timeanddate.com/docs/astro/), [API overview](https://dev.timeanddate.com/docs/overview), [API FAQ](https://dev.timeanddate.com/faq), [website policy](https://www.timeanddate.com/information/copyright.html) | Obtain API key/secret and paid license; review actual quotas/retention and third-party/derivative redistribution agreement; implement licensed API, no website scraping |

None has a configured credential or working adapter in this release. Unknown limits
or terms must be resolved against the specific access agreement rather than inferred
from the provider's inclusion in the requested plan.
