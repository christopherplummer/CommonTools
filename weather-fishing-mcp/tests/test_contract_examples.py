"""Validate documented SYNTHETIC contract shapes, not live availability."""

import json
from pathlib import Path

from weather_fishing.resolution import SolunarLocality, StationRelationship
from weather_fishing.resolution_models import (
    CollectionInput,
    ConditionsPackage,
    ResolutionResult,
    ResolveInput,
    StationRequest,
)


def test_synthetic_contract_examples_match_tool_models():
    path = Path(__file__).resolve().parents[1] / "docs/examples/resolution-contract.json"
    examples = json.loads(path.read_text(encoding="utf-8"))
    assert "SYNTHETIC" in examples["fixture_notice"]
    for key, model in [
        ("resolve_request", ResolveInput),
        ("ambiguous_response", ResolutionResult),
        ("station_request", StationRequest),
        ("collection_request", CollectionInput),
        ("collection_response", ConditionsPackage),
    ]:
        model.model_validate(examples[key])
    for row in examples["station_relationships"]:
        StationRelationship.model_validate(row)
    for row in examples["solunar_localities"]:
        SolunarLocality.model_validate(row)
