"""All fixtures are synthetic. They are never loaded by production adapters."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from weather_fishing.config import Settings
from weather_fishing.http import Fetched, ProviderError
from weather_fishing.service import Service


class FixtureHTTP:
    def __init__(self, settings):
        self.settings = settings
        self.responses = {}
        self.calls = []

    def add(self, suffix, body, provider=None):
        self.responses[suffix] = (provider, body)

    async def get(self, provider, url, params=None, **kwargs):
        self.calls.append((provider, url, params))
        for suffix, (expected, body) in self.responses.items():
            if url.endswith(suffix):
                assert expected is None or provider == expected
                if isinstance(body, Exception):
                    raise body
                return Fetched(
                    body if isinstance(body, bytes) else json.dumps(body).encode(),
                    url,
                    "2026-10-13T12:00:00+00:00",
                    {},
                )
        raise ProviderError("not_available", "No synthetic fixture configured for URL")

    async def close(self):
        pass


@pytest.fixture
def service(tmp_path):
    settings = Settings(_env_file=None, quota_database=tmp_path / "quota.sqlite3")
    return Service(settings, FixtureHTTP(settings))


@pytest.fixture
def point(service):
    service.http.add(
        "/points/38.9000,-77.0000",
        {
            "properties": {
                "forecast": "https://api.weather.gov/gridpoints/LWX/1,2/forecast",
                "forecastHourly": "https://api.weather.gov/gridpoints/LWX/1,2/forecast/hourly",
                "forecastGridData": "https://api.weather.gov/gridpoints/LWX/1,2",
                "observationStations": "https://api.weather.gov/gridpoints/LWX/1,2/stations",
                "gridId": "LWX",
                "gridX": 1,
                "gridY": 2,
                "timeZone": "America/New_York",
                "forecastZone": "https://api.weather.gov/zones/forecast/DCZ001",
            }
        },
    )
    return {"latitude": 38.9, "longitude": -77.0}


@pytest.fixture
def coops_station(service):
    service.http.add(
        "/stations/8443970.json",
        {
            "stations": [
                {
                    "id": "8443970",
                    "name": "SYNTHETIC Boston station",
                    "lat": 42.35,
                    "lng": -71.05,
                    "tidal": True,
                    "timezone": "EST",
                    "observedst": True,
                }
            ]
        },
    )
    service.http.add("/stations/8443970/datums.json", {"datums": [{"name": "MLLW"}]})
    return {"station_id": "8443970"}


@pytest.fixture
def ndbc_station(service):
    service.http.add(
        "/activestations.xml",
        b'<stations><station id="41009" name="SYNTHETIC buoy" '
        b'lat="28.5" lon="-80.2" owner="SYNTHETIC" met="y"/></stations>',
    )
    return {"station_id": "41009"}


@pytest.fixture
def solunar_page():
    # Generated fake clocks/rating for parser tests only, not provider evidence.
    def create(days=30, month="April 2025", city="beverly_hills", clock="11:30 PM-1:30 AM"):
        selects = "".join(
            f'<select name="ddl{key}"><option selected value="{value}">{value}</option></select>'
            for key, value in [
                ("Countries", "united_states"),
                ("States", "california"),
                ("Cities", city),
            ]
        )
        cells = "".join(
            f"""<td><h4>04/{day:02}/25</h4>
          <p><strong>Major Times</strong><br>{clock}</p>
          <p><strong>Minor Times</strong><br>--:-----:--</p>
          <p><strong>Day Rating</strong><br><span class="glyphicon-star"></span>SYNTHETIC</p>
          <p><strong>Sun Data</strong><br>Rise: 6:00 AM<br>Set: 6:00 PM</p>
          <p><strong>Moon Data</strong><br>Rise: --:--<br>Set: 1:00 PM<br>
          Over: 3:00 AM<br>Under: 3:00 PM</p>
          <p><strong>Moon Phase</strong><img alt="SYNTHETIC Moon 50%"/></p>
          <p><strong>Day Length</strong>12 hours</p></td>"""
            for day in range(1, days + 1)
        )
        return (selects + f"<h4>{month}</h4><table><tr>{cells}</tr></table>").encode()

    return create
