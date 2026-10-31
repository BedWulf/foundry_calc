"""Verify independently sourced furnace reference specifications remain immutable."""
import json
from pathlib import Path


REFERENCE = (Path(__file__).resolve().parents[1] / "data" / "verified_references" /
             "indotherm_casting_units.json")


def test_manufacturer_reference_documented_and_not_auto_selected():
    data = json.loads(REFERENCE.read_text(encoding="utf-8"))
    assert data["usage_policy"] == "reference_only_no_automatic_selection"
    assert data["source"]["url"].startswith("https://")
    assert data["conditions"]["temperature_c"] == 1675
    assert data["conditions"]["material"] == "steel scrap"
    assert len(data["entries"]) == 2
    for entry in data["entries"]:
        assert entry["verification_status"] == "manufacturer_catalog_verified"
        assert entry["operating_validation_status"] == "not_validated"
        assert entry["capacity_kg"] > 0 and entry["power_kw"] > 0
        assert entry["published_melting_rate_kg_h"] > 0
        assert entry["source_fields"]


def test_reference_rows_are_the_manufacturer_published_pairs():
    data = json.loads(REFERENCE.read_text(encoding="utf-8"))
    rows = [(e["capacity_kg"], e["power_kw"], e["published_melting_rate_kg_h"])
            for e in data["entries"]]
    assert rows == [(1000, 500, 875), (2000, 1000, 1850)]
