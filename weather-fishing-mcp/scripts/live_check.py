"""Opt-in live checks; no fixture fallback and no credential acquisition.

Writes only compact verification metadata. Does not persist provider content.
Solunar inspection tests availability/parser only, not production redistribution rights.
"""

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from weather_fishing.adapters.solunar import parse_month
from weather_fishing.config import Settings
from weather_fishing.models import SolunarInput
from weather_fishing.service import Service


async def check(args):
    service = Service(Settings())
    checks = [
        (
            "nws_station_discovery",
            "discover_locations",
            {"provider": "nws", "location": {"latitude": 38.9, "longitude": -77.0}, "limit": 5},
        ),
        (
            "nws_forecast",
            "get_forecast",
            {
                "location": {"latitude": 38.9, "longitude": -77.0},
                "fields": ["temperature", "windSpeed"],
                "limit": 3,
            },
        ),
        (
            "nws_active_alerts",
            "get_alerts",
            {"location": {"latitude": 38.9, "longitude": -77.0}, "limit": 3},
        ),
        (
            "nws_recent_observations",
            "get_observations",
            {
                "provider": "nws",
                "location": {"station_id": "KDCA"},
                "fields": ["temperature", "windSpeed"],
                "units": "source",
                "limit": 2,
            },
        ),
        (
            "nws_marine_zone",
            "get_marine_forecast",
            {"location": {"zone_id": "ANZ230"}, "units": "source", "limit": 2},
        ),
        (
            "nws_marine_grid",
            "get_marine_forecast",
            {
                "location": {"latitude": 42.25, "longitude": -70.6},
                "units": "source",
                "fields": ["waveHeight", "windSpeed"],
                "limit": 3,
            },
        ),
        (
            "coops_station_discovery",
            "discover_locations",
            {"provider": "coops", "location": {"latitude": 42.35, "longitude": -71.05}, "limit": 3},
        ),
        (
            "coops_tide_predictions",
            "get_tides_currents",
            {
                "location": {"station_id": "8443970"},
                "start_date": "2025-04-01",
                "end_date": "2025-04-02",
                "limit": 20,
            },
        ),
        (
            "coops_water_level_history",
            "get_tides_currents",
            {
                "location": {"station_id": "8443970"},
                "product": "hourly_height",
                "start_date": "2025-04-01",
                "fields": ["height", "quality"],
                "limit": 3,
            },
        ),
        (
            "coops_current_predictions",
            "get_tides_currents",
            {
                "location": {"station_id": "EPT0003"},
                "product": "currents_predictions",
                "bin": 14,
                "interval": "10",
                "start_date": "2025-04-01",
                "limit": 3,
            },
        ),
        (
            "coops_current_observations",
            "get_tides_currents",
            {
                "location": {"station_id": "cb0102"},
                "product": "currents",
                "bin": 1,
                "start_date": datetime.now(UTC).date().isoformat(),
                "limit": 3,
            },
        ),
        (
            "coops_historical_currents",
            "get_tides_currents",
            {
                "location": {"station_id": "CFR1624"},
                "product": "currents",
                "bin": 9,
                "start_date": "2016-04-01",
                "limit": 3,
            },
        ),
        (
            "ndbc_station_discovery",
            "discover_locations",
            {"provider": "ndbc", "location": {"latitude": 28.5, "longitude": -80.2}, "limit": 3},
        ),
        (
            "ndbc_realtime",
            "get_observations",
            {
                "provider": "ndbc",
                "location": {"station_id": "41009"},
                "fields": ["WTMP", "WSPD", "WVHT"],
                "limit": 3,
            },
        ),
        (
            "ndbc_2025_archive",
            "get_observations",
            {
                "provider": "ndbc",
                "location": {"station_id": "41009"},
                "historical": True,
                "start_date": "2025-04-01",
                "fields": ["WTMP", "WSPD", "WVHT"],
                "limit": 3,
            },
        ),
        (
            "fisheries_species",
            "get_fishing_info",
            {
                "location": {"city": "Boston", "country": "US"},
                "species": "atlantic-cod",
                "topic": "biology",
                "limit": 1,
            },
        ),
        (
            "fisheries_directory",
            "discover_locations",
            {"provider": "fisheries", "location": {"city": "Boston"}, "limit": 3},
        ),
        (
            "ncei_history",
            "get_observations",
            {
                "provider": "ncei",
                "location": {"station_id": "GHCND:USW00014739"},
                "start_date": "2025-04-01",
                "fields": ["TMAX"],
                "limit": 3,
            },
        ),
    ]
    report = {"checked_at": datetime.now(UTC).isoformat(), "fixture_data_used": False, "checks": []}
    try:
        for name, tool, arguments in checks:
            if name.startswith("ncei") and not service.settings.ncei_token.get_secret_value():
                entry = {
                    "check": name,
                    "verified": False,
                    "status": "not_run",
                    "reasons": ["NCEI token not configured"],
                }
            else:
                r = await service.call(tool, arguments)
                entry = {
                    "check": name,
                    "verified": r.status != "unavailable"
                    and (bool(r.records) or name == "nws_active_alerts"),
                    "status": r.status,
                    "record_count": len(r.records),
                    "source_url": r.source_url,
                    "retrieved_at": r.retrieved_at,
                    "reasons": r.reasons,
                    "missing_fields": r.missing_fields,
                    "units": r.units,
                    "kind": r.kind,
                }
            report["checks"].append(entry)
            print(json.dumps(entry), flush=True)
        if args.inspect_solunar:
            q = SolunarInput(
                location={
                    "country": "united_states",
                    "state": "california",
                    "city": "beverly_hills",
                },
                year=2025,
                month=4,
            )
            url = "https://solunarforecast.com/hunting_fishing/best_times/table/united_states/california/beverly_hills/4/2025/"
            try:
                fetched = await service.http.get("solunar", url, ttl=0)
                selected, rows, gaps, missing = parse_month(fetched.body, q)
                entry = {
                    "check": "solunar_april_2025_public_table_inspection",
                    "verified": bool(rows) and not gaps,
                    "status": "complete" if not gaps else "partial",
                    "record_count": len(rows),
                    "source_url": url,
                    "retrieved_at": fetched.retrieved_at,
                    "verified_location": selected,
                    "missing_dates": gaps,
                    "missing_fields": sorted(set(missing)),
                    "qualifications": [
                        (
                            "Availability/parser verification only, not commercial rights or "
                            "source timezone verification"
                        ),
                        (
                            "No production permission flag was set; only one public monthly table "
                            "was inspected"
                        ),
                    ],
                }
            except Exception as exc:
                entry = {
                    "check": "solunar_april_2025_public_table_inspection",
                    "verified": False,
                    "status": "unavailable",
                    "reason": getattr(exc, "code", type(exc).__name__),
                }
            report["checks"].append(entry)
            print(json.dumps(entry), flush=True)
    finally:
        await service.close()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--inspect-solunar",
        action="store_true",
        help=("Inspect one public April 2025 table without enabling production adapter"),
    )
    parser.add_argument("--output", default="verification/live-check.json")
    asyncio.run(check(parser.parse_args()))


if __name__ == "__main__":
    main()
