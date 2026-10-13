"""Opt-in actual MCP/public-provider check. Saves metadata only; NEVER uses fixtures."""

import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    root = Path(__file__).resolve().parents[1]
    report = {
        "checked_at": datetime.now(UTC).isoformat(),
        "fixture_data_used": False,
        "scope": "Actual SDK stdio/text result and public NOAA calls; not LM Studio UI",
    }
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(root / "scripts/run_stdio.py")],
        cwd=str(root),
        env={
            "PYTHONPATH": str(root / "src"),
            "WF_TEXT_RESULTS": "true",
            "WF_SOLUNAR_PERMISSION_REFERENCE": "",
            "WF_NCEI_TOKEN": "",
        },
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=timedelta(minutes=5)) as client:
            await client.initialize()
            report["tools_discovered"] = len((await client.list_tools()).tools)
            resolved = await client.call_tool(
                "resolve_location", {"coordinates": {"latitude": 42.35, "longitude": -71.05}}
            )
            body = resolved.structuredContent
            report["resolution"] = {
                "status": body["status"],
                "state": body["state"],
                "context": body.get("context"),
                "reasons": body["reasons"],
                "text_equals_structured": json.loads(resolved.content[0].text) == body,
            }
            if body.get("context") and body["context"].get("timezone"):
                window = {"local_date": (datetime.now(UTC) + timedelta(days=1)).date().isoformat()}
                result = await client.call_tool(
                    "collect_resolved_conditions",
                    {
                        "context": body["context"],
                        "window": window,
                        "limit_per_category": 3,
                        "permitted_providers": ["nws", "coops", "solunar"],
                    },
                )
                package = result.structuredContent
                report["collection"] = {
                    "status": package["status"],
                    "window": window,
                    "text_equals_structured": json.loads(result.content[0].text) == package,
                    "json_bytes": len(result.content[0].text.encode()),
                    "categories": {
                        name: {
                            "retrieval_status": c["retrieval_status"],
                            "relevance_status": c["relevance_status"],
                            "coverage_status": c["coverage_status"],
                            "failures": c["failures"],
                            "coverage_gaps": c["coverage_gaps"],
                            "records": sum(len(r["records"]) for r in c["results"]),
                            "candidate_count": len(c["selection"]["candidates"])
                            if c["selection"]
                            else 0,
                            "sources": [r["source_url"] for r in c["results"]],
                            "all_records_have_evidence": all(
                                row["evidence_refs"] for r in c["results"] for row in r["records"]
                            ),
                        }
                        for name, c in package["categories"].items()
                    },
                }
            tide = await client.call_tool(
                "get_tides_currents",
                {
                    "location": {"station_id": "8443970"},
                    "start_date": "2025-04-01",
                    "timezone": "America/New_York",
                    "limit": 3,
                },
            )
            t = tide.structuredContent
            report["explicit_station_compatibility"] = {
                "status": t["status"],
                "source_url": t["source_url"],
                "reasons": t["reasons"],
                "record_count": len(t["records"]),
                "datum": t["datum"],
                "has_raw_values": all(r["source_values"] for r in t["records"]),
                "text_equals_structured": json.loads(tide.content[0].text) == t,
                "qualification": "Caller-selected station; local suitability unverified",
            }
    # Remove the integrity receipt from metadata; it is ephemeral to the ended server process.
    if report["resolution"]["context"]:
        report["resolution"]["context"].pop("receipt", None)
    output = root / "verification" / "resolution-live-check.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
