import json
from pathlib import Path
from core.alloy_data_audit import audit_alloy_references

ROOT = Path(__file__).resolve().parents[1]

def test_verified_designations_do_not_automatically_verify_process_data():
    reference = json.loads((ROOT / "data/verified_references/alloy_standards.json").read_text(encoding="utf-8"))
    alloys = json.loads((ROOT / "data/materials/alloys.json").read_text(encoding="utf-8"))
    issues = audit_alloy_references(alloys, reference)
    assert len(alloys["alloys"]) == 17
    assert len(reference["grades"]) == 10
    assert not any(i["code"] == "STANDARD_MISMATCH" for i in issues)
    assert any(i["code"] == "GRADE_NOT_VERIFIED" for i in issues)
    assert any(i["code"] == "PROCESS_PROPERTY_UNVERIFIED" for i in issues)

def test_mismatched_standard_is_flagged():
    reference = {"sources":[{"id":"std","designation":"ГОСТ X"}],
                 "grades":[{"category":"steel","name":"20Л","standard_id":"std"}]}
    alloys = {"alloys":[{"id":"test","name":"20Л","category":"steel","gost":"ГОСТ Y"}]}
    assert "STANDARD_MISMATCH" in {i["code"] for i in audit_alloy_references(alloys, reference)}
