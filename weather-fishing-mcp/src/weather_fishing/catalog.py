"""Capability plan, reviewed interfaces and unresolved rights. Not a license grant."""

CATALOG = {
    "nws": {
        "name": "US National Weather Service",
        "implemented": True,
        "coverage": "NWS US/territory point and marine-zone coverage; checked upstream",
        "capabilities": [
            "forecast",
            "marine_forecast",
            "active_alerts",
            "recent_observations",
            "station_discovery",
        ],
        "authentication": "Identifying User-Agent; no key currently",
        "rate_limit": (
            "Provider numeric limit unpublished; local 1 request/s, failure cooldown >=60s"
        ),
        "licensing": (
            "Open data, any lawful purpose; credit NWS, no implied endorsement; "
            "third-party exceptions"
        ),
        "retention": (
            "No response persistence; RAM <=300s or stricter upstream headers; alerts <=30s"
        ),
        "documentation": "https://www.weather.gov/documentation/services-web-api",
        "terms": "https://www.weather.gov/disclaimer",
        "limitations": ["No archived forecasts", "No implicit geocoding"],
    },
    "coops": {
        "name": "NOAA Tides & Currents",
        "implemented": True,
        "coverage": (
            "CO-OPS stations, mostly US coast/territories and Great Lakes; not all "
            "products at all stations"
        ),
        "capabilities": [
            "tide_predictions",
            "water_level_observations",
            "current_observations",
            "current_predictions",
            "station_discovery",
        ],
        "authentication": "Public GET API; application identifier supplied",
        "rate_limit": (
            "Numeric request-rate ceiling not found; local 1 request/s; <=30-day tool range"
        ),
        "licensing": (
            "NOAA government information policy, dataset/partner exceptions; credit CO-OPS"
        ),
        "retention": "RAM <=360s, no persistent responses; upstream headers can shorten/disable",
        "documentation": "https://api.tidesandcurrents.noaa.gov/api/prod/",
        "terms": "https://oceanservice.noaa.gov/about/faq.html",
        "limitations": [
            "Preserve datum",
            "Current products require explicit bin",
            "Station distance is representative only",
        ],
    },
    "ncei": {
        "name": "NOAA NCEI CDO v2",
        "implemented": True,
        "coverage": "GHCND/GSOM/GSOY international station records; dataset/station-dependent",
        "capabilities": ["historical_observations", "station_discovery"],
        "authentication": "WF_NCEI_TOKEN required",
        "rate_limit": (
            "Documented 5/s and 10000/day per token; local 1/s and persisted "
            "9000 attempts across current/previous UTC dates"
        ),
        "licensing": (
            "NOAA/third-party dataset rights must be checked; no blanket license for all holdings"
        ),
        "retention": "No response persistence; RAM <=3600s; no general CDO retention term found",
        "documentation": "https://www.ncei.noaa.gov/cdo-web/webservices/v2",
        "terms": "https://www.ncei.noaa.gov/archive",
        "limitations": [
            "Dataset-specific dates/scales",
            "No archived forecasts",
            "Live calls require token",
        ],
    },
    "ndbc": {
        "name": "NOAA NDBC",
        "implemented": True,
        "coverage": (
            "Active NDBC/partner station network including overseas stations; not "
            "uniform global coverage"
        ),
        "capabilities": ["buoy_observations", "historical_observations", "station_discovery"],
        "authentication": "Public official HTTPS flat files; no API key",
        "rate_limit": "Minimize polling; most stations hourly; local 1/s with RAM cache <=3600s",
        "licensing": (
            "NOAA federal-data policy; contributing operator/source restrictions may apply"
        ),
        "retention": (
            "No persistent records; no explicit general retention limit found; RAM <=3600s"
        ),
        "documentation": "https://www.ndbc.noaa.gov/faq/rt_data_access.shtml",
        "terms": "https://www.noaa.gov/disclaimer",
        "limitations": [
            "Standard meteorological data only",
            "Retired stations without active metadata unavailable",
            "Station IDs/deployments can move",
            "Monthly archives may lag",
        ],
    },
    "fisheries": {
        "name": "NOAA Fisheries",
        "implemented": True,
        "coverage": (
            "US marine species/fishery background; not comprehensive freshwater or "
            "verified regulations"
        ),
        "capabilities": ["species_information", "fishing_background", "species_directory_links"],
        "authentication": (
            "Public official species pages; no documented generic species API verified"
        ),
        "rate_limit": "Numeric ceiling not found; local 1/s and RAM cache <=3600s",
        "licensing": (
            "Government text generally public domain in US; preserve credit; third-party exceptions"
        ),
        "retention": "No persistent pages; no general page-retention term found; RAM <=3600s",
        "documentation": "https://www.fisheries.noaa.gov/species-directory",
        "terms": "https://www.fisheries.noaa.gov/national/about-us/website-policies-and-disclaimers",
        "limitations": [
            "Current profile excerpts only",
            "No legal/regulatory verification",
            "Directory links not exhaustive",
        ],
    },
    "solunar": {
        "name": "SolunarForecast.com",
        "implemented": True,
        "coverage": (
            "Country/state/city monthly tables offered worldwide; each request "
            "identity/date checked"
        ),
        "capabilities": [
            "solunar_periods",
            "solunar_ratings",
            "sun_moon_fields",
            "city_verification",
        ],
        "authentication": "Public monthly table; no official automation API verified",
        "rate_limit": (
            "Published numeric rate not found; local 1/s, one monthly table/call, no retries"
        ),
        "licensing": (
            "Personal noncommercial terms restrict copying/redistribution; "
            "permission reference required"
        ),
        "retention": (
            "No response cache or persistence; redistribution/retention requires "
            "actual agreement review"
        ),
        "documentation": "https://solunarforecast.com/solunartable-city.aspx",
        "terms": "https://solunarforecast.com/termsofuse.aspx",
        "limitations": [
            "Sole solunar provider; no fallback",
            "April 2025 verified for Beverly Hills only",
            "Source city IANA timezone not provided by site; operator verification required",
        ],
    },
    "metoffice": {
        "name": "UK Met Office",
        "implemented": False,
        "coverage": "UK/weather/marine per subscribed product",
        "capabilities": ["planned_weather", "planned_marine"],
        "authentication": "DataHub subscription and apikey header",
        "rate_limit": "Subscription/product specific; not configured",
        "licensing": (
            "Commercial use subject to DataHub agreement; Powered by Met Office data attribution"
        ),
        "retention": "Not reviewed for an actual subscribed product; disabled",
        "documentation": "https://datahub.metoffice.gov.uk/support/faqs",
        "terms": "https://www.metoffice.gov.uk/binaries/content/assets/metofficegovuk/pdf/data/met-office-weatherdatahub-terms-and-conditions.pdf",
        "limitations": [
            (
                "Disabled plan only; access/licensing/product review and adapter "
                "implementation outstanding"
            )
        ],
    },
    "bom": {
        "name": "Australian Bureau of Meteorology",
        "implemented": False,
        "coverage": "Australia; dependent on subscribed weather/marine products",
        "capabilities": ["planned_weather", "planned_marine"],
        "authentication": "Paid subscription access to be reviewed",
        "rate_limit": "Unverified for a specific product; disabled",
        "licensing": (
            "Some free forecast/warning/observation text products are not for commercial use"
        ),
        "retention": "Product agreement not reviewed; disabled",
        "documentation": "https://www.bom.gov.au/resources/data-services",
        "terms": "https://www.bom.gov.au/other/copyright.shtml",
        "limitations": ["Disabled plan only; requires access/licensing review and implementation"],
    },
    "tides4fishing": {
        "name": "Tides4Fishing",
        "implemented": False,
        "coverage": "Planned tides only at supported locations",
        "capabilities": ["planned_tides_only"],
        "authentication": "No official API/access rights verified",
        "rate_limit": "Not verified; disabled",
        "licensing": "Commercial retrieval/redistribution rights not established",
        "retention": "Not established; disabled",
        "documentation": "https://tides4fishing.com/",
        "terms": "https://tides4fishing.com/",
        "limitations": ["Never a solunar fallback", "Disabled plan only; no scraping adapter"],
    },
    "timeanddate": {
        "name": "timeanddate.com licensed API",
        "implemented": False,
        "coverage": "Planned global astronomy via subscribed API",
        "capabilities": ["planned_astronomy"],
        "authentication": "API access key and secret key",
        "rate_limit": "Plan specific; not configured",
        "licensing": (
            "Paid API; third-party databases/derivative redistribution may require "
            "separate agreement"
        ),
        "retention": "Actual licensed API agreement not reviewed; disabled",
        "documentation": "https://dev.timeanddate.com/docs/astro/",
        "terms": "https://dev.timeanddate.com/faq",
        "limitations": [
            "No website scraping",
            "Disabled plan only; licensing/access review and implementation outstanding",
        ],
    },
}


def enabled(provider, settings):
    if not CATALOG[provider]["implemented"]:
        return False
    if provider == "ncei":
        return bool(settings.ncei_token.get_secret_value())
    if provider == "solunar":
        return bool(settings.solunar_permission_reference)
    return True
