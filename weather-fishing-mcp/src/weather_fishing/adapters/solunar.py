import calendar
import re
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from lxml import html

from ..http import ProviderError
from ..models import Record
from ..timeutil import finish
from .base import Adapter

BASE = "https://solunarforecast.com"
ASTRO_FIELDS = [
    "sunrise",
    "sunset",
    "moonrise",
    "moonset",
    "moon_over",
    "moon_under",
    "moon_phase",
    "moon_illumination_percent",
    "day_length",
]


def slug(value: str | None):
    if not value:
        raise ProviderError("location_required", "Solunar requires country, state/region and city")
    value = value.lower().replace(" ", "_")
    if not re.fullmatch(r"[a-z0-9_]+", value):
        raise ProviderError(
            "location_unresolved", "Use the provider's exact country/state/city slugs"
        )
    return value


def local_event(raw: str, day: date, source_zone: str | None, requested_zone: str, day_offset=0):
    if not raw or "--" in raw:
        return {"source_time": raw, "time": None, "event": "no_event"}
    clock = datetime.strptime(raw.strip(), "%I:%M %p").time()
    naive = datetime.combine(day + timedelta(days=day_offset), clock)
    if source_zone is None:
        return {"source_time": raw, "time": None, "event": "source_timezone_unverified"}
    zone = ZoneInfo(source_zone)
    candidates = []
    for fold in [0, 1]:
        stamp = naive.replace(tzinfo=zone, fold=fold)
        if stamp.astimezone(UTC).astimezone(zone).replace(tzinfo=None) == naive:
            if not any(s.astimezone(UTC) == stamp.astimezone(UTC) for s in candidates):
                candidates.append(stamp)
    if len(candidates) != 1:
        return {"source_time": raw, "time": None, "event": "ambiguous_or_nonexistent_local_time"}
    return {
        "source_time": raw,
        "time": candidates[0].astimezone(ZoneInfo(requested_zone)).isoformat(),
    }


def parse_month(body: bytes, q):
    root = html.fromstring(body)
    expected = {
        "Countries": slug(q.location.country),
        "States": slug(q.location.state),
        "Cities": slug(q.location.city),
    }
    selected = {}
    for name, value in expected.items():
        options = root.xpath(f'//select[contains(@name,"ddl{name}")]/option[@selected]')
        if len(options) != 1 or options[0].get("value") != value:
            raise ProviderError(
                "location_mismatch", "Provider returned a default or different location"
            )
        selected[name] = options[0].text_content().strip()
    month_name = f"{calendar.month_name[q.month]} {q.year}"
    if not any(e.text_content().strip() == month_name for e in root.xpath("//h4")):
        raise ProviderError("month_mismatch", "Provider returned a different month or layout")
    rows = []
    seen = set()
    missing = []
    for cell in root.xpath("//td[h4]"):
        headings = cell.xpath("./h4")
        if not headings:
            continue
        match = re.search(r"\b(\d{2}/\d{2}/\d{2})\b", headings[0].text_content())
        if not match:
            continue
        # Explicit requested century avoids strptime's 1969/2068 two-digit cutoff.
        m, d, yy = map(int, match[1].split("/"))
        if yy != q.year % 100:
            raise ProviderError("month_mismatch", "Source year does not match requested year")
        day = date(q.year, m, d)
        if (day.year, day.month) != (q.year, q.month) or day in seen:
            raise ProviderError("month_mismatch", "Unexpected or duplicate date in monthly table")
        seen.add(day)
        sections = {}
        for p in cell.xpath("./p"):
            labels = p.xpath("./strong")
            if not labels:
                continue
            title = labels[0].text_content().strip()
            copy = html.fromstring(html.tostring(p))
            # Only remove the heading. Later <strong> elements mark heightened
            # periods/events and contain actual source data.
            copy.xpath("./strong")[0].drop_tree()
            text = " ".join(copy.text_content().split())
            sections[title] = (text, p)

        def text(name, sections=sections):
            return sections.get(name, ("", None))[0]

        values = {
            "date": day.isoformat(),
            "rating": text("Day Rating") or None,
            "rating_stars": len(
                sections["Day Rating"][1].xpath('.//span[contains(@class,"glyphicon-star")]')
            )
            if "Day Rating" in sections
            else None,
            "major_periods": [],
            "minor_periods": [],
        }
        for label, key in [("Major Times", "major_periods"), ("Minor Times", "minor_periods")]:
            periods = re.findall(r"(\d{1,2}:\d{2} [AP]M)\s*-\s*(\d{1,2}:\d{2} [AP]M)", text(label))
            for start, end in periods:
                crosses = datetime.strptime(end, "%I:%M %p") < datetime.strptime(start, "%I:%M %p")
                values[key].append(
                    {
                        "start": local_event(start, day, q.source_timezone, q.timezone),
                        "end": local_event(end, day, q.source_timezone, q.timezone, int(crosses)),
                        "crosses_midnight": crosses,
                    }
                )
            if label not in sections:
                missing.append(key)
        for label, prefix in [("Sun Data", "sun"), ("Moon Data", "moon")]:
            for name, key in [
                ("Rise", prefix + "rise"),
                ("Set", prefix + "set"),
                ("Over", prefix + "_over"),
                ("Under", prefix + "_under"),
            ]:
                if prefix == "sun" and name in {"Over", "Under"}:
                    continue
                m = re.search(name + r":\s*(\d{1,2}:\d{2} [AP]M|--:--)", text(label))
                values[key] = local_event(m[1], day, q.source_timezone, q.timezone) if m else None
                if m is None:
                    missing.append(key)
        phase_section = sections.get("Moon Phase", ("", None))
        images = phase_section[1].xpath(".//img/@alt") if phase_section[1] is not None else []
        phase = images[0] if images else phase_section[0]
        m = re.search(r"(\d+(?:\.\d+)?)%", phase)
        values["moon_illumination_percent"] = float(m[1]) if m else None
        # Retain the source's descriptive phase; do not calculate a substitute.
        values["moon_phase"] = phase or None
        values["day_length"] = text("Day Length") or None
        if values["rating"] is None:
            missing.append("rating")
        qualifications = []
        for v in values.values():
            if isinstance(v, dict) and v.get("event") == "ambiguous_or_nonexistent_local_time":
                qualifications.append("Source local event cannot uniquely map across DST")
        rows.append(
            Record(source_time=day.isoformat(), values=values, qualifications=qualifications)
        )
    expected_days = {
        date(q.year, q.month, d) for d in range(1, calendar.monthrange(q.year, q.month)[1] + 1)
    }
    gaps = sorted(d.isoformat() for d in expected_days - seen)
    return selected, rows, gaps, missing


class Solunar(Adapter):
    provider = "solunar"
    home = BASE + "/solunartable-city.aspx"
    attribution = "Source: SolunarForecast.com; all rights reserved, use requires permission"

    def enabled(self):
        if not self.http.settings.solunar_permission_reference:
            raise ProviderError(
                "license_review_required",
                (
                    "SolunarForecast terms restrict commercial use/redistribution. Set an "
                    "operator permission "
                    "reference only after confirming rights for automated retrieval and your use"
                ),
            )

    async def monthly(self, q, astronomy=False, discovery=False):
        self.enabled()
        country, state, city = [
            slug(v) for v in [q.location.country, q.location.state, q.location.city]
        ]
        url = (
            f"{BASE}/hunting_fishing/best_times/table/{country}/{state}/{city}/{q.month}/{q.year}/"
        )
        fetched = await self.http.get(self.provider, url, ttl=0)
        selected, rows, gaps, missing = parse_month(fetched.body, q)
        result = self.result(
            q,
            "discovery" if discovery else "prediction",
            fetched,
            source_timezone=q.source_timezone or "unverified source city local clock",
            units={
                "times": "source local HH:MM AM/PM; offset ISO if source_timezone supplied",
                "moon_illumination_percent": "percent",
                "rating_stars": "source icons",
            },
            qualifications=[
                "One country/state/city monthly table; never a second solunar provider",
                "Solunar periods/ratings are provider predictions, not observed fish activity",
                (
                    "Source local calendar dates are preserved even when event timezone "
                    "conversion changes day"
                ),
                (
                    "Historical table regenerated/retrieved now; not an archived forecast "
                    "issued in 2025"
                ),
            ],
        )
        result.location.update(
            {
                "verified_country": selected["Countries"],
                "verified_state": selected["States"],
                "verified_city": selected["Cities"],
                "representative": True,
                "relevance": "Selected city, not coordinate-specific conditions",
            }
        )
        result.missing_fields = sorted(
            set(missing).intersection(q.fields) if q.fields else set(missing)
        )
        if gaps:
            result.reasons.append("Missing source dates: " + ", ".join(gaps))
        if not q.source_timezone:
            result.reasons.append("Source timezone unverified; times kept as source strings")
            result.missing_fields.append("verified_source_timezone")
        else:
            result.qualifications.append(
                "Source IANA timezone supplied by operator; site has no verified IANA metadata"
            )
        if q.location.latitude is not None:
            result.reasons.append(
                "City selection verified; geographic relevance to coordinates is unverified"
            )
        if discovery:
            rows = [Record(values=result.location)]
        else:
            if q.start_date:
                rows = [
                    r
                    for r in rows
                    if q.start_date <= date.fromisoformat(r.source_time) <= q.end_date
                ]
            if astronomy:
                for row in rows:
                    row.values = {k: row.values.get(k) for k in ASTRO_FIELDS}
                result.missing_fields = [
                    f
                    for f in result.missing_fields
                    if f in ASTRO_FIELDS or f == "verified_source_timezone"
                ]
        return finish(result, q, rows)
