"""Catalogue validation must not conflate plausible numbers with verified data."""
import copy
import json
from pathlib import Path

from core.equipment_data_audit import audit_molding_catalog


CATALOG = Path(__file__).resolve().parents[1] / "data" / "equipment" / "molding_lines.json"


def test_all_catalogue_models_have_provenance_and_are_not_falsely_verified():
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    findings = audit_molding_catalog(data)
    assert len(data["lines"]) == 5
    assert not [f for f in findings if f["code"] in {
        "INVALID_CATALOG", "INVALID_LINE", "DUPLICATE_ID",
        "MISSING_SPEC", "INVALID_POSITIVE", "INVALID_DIMENSIONS",
        "INVALID_HEIGHTS", "INVALID_MASS_RANGE", "MISSING_PROVENANCE",
        "MISSING_SOURCE", "INVALID_SOURCE_STATUS", "UNSUPPORTED_VERIFIED",
    }]
    assert len([f for f in findings if f["code"] == "UNVERIFIED_SOURCE"]) == 25


def test_duplicate_id_and_invalid_speed_are_detected_without_mutation():
    original = json.loads(CATALOG.read_text(encoding="utf-8"))
    damaged = copy.deepcopy(original)
    damaged["lines"][1]["id"] = damaged["lines"][0]["id"]
    damaged["lines"][0]["specs"]["nominal_productivity_molds_h"] = float("nan")
    before_count = len(damaged["lines"])
    codes = {f["code"] for f in audit_molding_catalog(damaged)}
    assert {"DUPLICATE_ID", "INVALID_POSITIVE"} <= codes
    assert len(damaged["lines"]) == before_count


def test_unjustified_verified_flag_is_rejected():
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    record = data["lines"][0]["provenance"]["max_mold_metal_kg"]
    record["verification_status"] = "verified"
    assert "UNSUPPORTED_VERIFIED" in {
        f["code"] for f in audit_molding_catalog(data)
    }
