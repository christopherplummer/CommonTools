from lxml import html

from ..http import ProviderError
from ..models import Record
from ..timeutil import finish
from .base import Adapter

BASE = "https://www.fisheries.noaa.gov"
TOPICS = {
    "biology": ["biology"],
    "habitat": ["where-they-live", "habitat"],
    "management": ["management"],
    "harvest": ["harvest"],
    "species": [
        "biology",
        "where-they-live",
        "population",
        "population-status",
        "management",
        "harvest",
        "appearance",
    ],
}


class Fisheries(Adapter):
    provider = "fisheries"
    home = BASE + "/species-directory"
    attribution = "Courtesy: National Oceanic and Atmospheric Administration, NOAA Fisheries"

    async def discover(self, q):
        fetched = await self.http.get(self.provider, self.home)
        root = html.fromstring(fetched.body)
        records = {}
        for a in root.xpath('//main//a[starts-with(@href,"/species/")]'):
            href = a.get("href")
            slug = href.removeprefix("/species/")
            if "/" in slug or "?" in slug:
                continue
            records[slug] = Record(
                values={
                    "species": slug,
                    "name": " ".join(a.text_content().split()),
                    "source_url": BASE + href,
                }
            )
        result = self.result(
            q,
            "discovery",
            fetched,
            qualifications=[
                "Directory landing-page links only; not an exhaustive species catalogue",
                (
                    "US marine species information; geographic occurrence is not inferred "
                    "from location"
                ),
            ],
        )
        result.reasons.append("Directory may have additional dynamic/paginated listings")
        return finish(result, q, list(records.values()))

    async def fishing(self, q):
        if q.start_date:
            raise ProviderError(
                "unsupported_product",
                "Species profiles are current pages, not dated regulation archives",
            )
        if q.location.country and q.location.country.lower() not in {
            "us",
            "usa",
            "united states",
            "united_states",
            "united states of america",
        }:
            raise ProviderError(
                "unsupported_coverage", "NOAA Fisheries adapter provides US marine information"
            )
        fetched = await self.http.get(self.provider, BASE + "/species/" + q.species)
        root = html.fromstring(fetched.body)
        titles = root.xpath("//main//h1")
        if not titles:
            raise ProviderError("invalid_response", "Species profile title not found")
        result = self.result(
            q,
            "information",
            fetched,
            source_timezone="not applicable",
            units={"text": "source prose; quantities retain source units"},
            qualifications=[
                "Marine species/fishery background; not comprehensive freshwater coverage",
                (
                    "Not verified current regulations, legal advice, catch permissions, "
                    "bag or size limits"
                ),
                "No local occurrence or fishing suitability inferred from supplied location",
                "Source excerpts are normalized text, not an official republished product",
            ],
        )
        modified = root.xpath('//meta[@property="article:modified_time"]/@content')
        result.publication_time = modified[0] if modified else None
        result.location["coverage"] = (
            "US marine species/fisheries information; local relevance unverified"
        )
        rows = []
        for field in TOPICS[q.topic]:
            nodes = root.xpath(
                f'//main//*[contains(concat(" ",normalize-space(@class)," "),'
                f'" field--name-field-{field} ")]'
            )
            if not nodes:
                result.missing_fields.append(field)
                continue
            text = " ".join(nodes[0].text_content().split())
            if len(text) > 4000:
                result.reasons.append(f"{field} excerpt truncated at 4000 characters")
            rows.append(
                Record(
                    values={
                        "species": titles[0].text_content().strip(),
                        "topic": field,
                        "text": text[:4000],
                    }
                )
            )
        return finish(result, q, rows)
