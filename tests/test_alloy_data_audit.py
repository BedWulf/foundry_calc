"""Normative grade designations are not permission to invent physical data."""
import json
from pathlib import Path

from core.alloy_data_audit import audit_alloy_references, validate_grade_index

ROOT = Path(__file__).resolve().parents[1]


def _read(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def test_verified_designations_do_not_automatically_verify_process_data():
    reference = _read("data/verified_references/alloy_standards.json")
    alloys = _read("data/materials/alloys.json")
    assert len(alloys["alloys"]) == 17
    assert len(reference["grades"]) == 96
    assert len(reference["sources"]) == 5
    assert validate_grade_index(reference) == []
    findings = audit_alloy_references(alloys, reference)
    # The old AЛ2/4/9 records use ГОСТ 2685-63; new canonical/alias
    # names are recorded under ГОСТ 1583-93, so automatic migration is unsafe.
    conflicting = {x["alloy_id"] for x in findings
                   if x["code"] == "STANDARD_MISMATCH"}
    assert conflicting == {"aluminum_AL2", "aluminum_AL4", "aluminum_AL9"}
    assert not [x for x in findings if x["code"] == "GRADE_NOT_VERIFIED"]
    assert sum(x["code"] == "PROCESS_PROPERTY_UNVERIFIED"
               for x in findings) >= len(alloys["alloys"])


def test_mismatched_standard_is_flagged():
    reference = {"sources": [{"id": "std", "designation": "ГОСТ X"}],
                 "grades": [{"category": "steel", "name": "20Л",
                             "standard_id": "std"}]}
    alloys = {"alloys": [{"id": "test", "name": "20Л", "category": "steel",
                         "gost": "ГОСТ Y"}]}
    assert "STANDARD_MISMATCH" in {
        i["code"] for i in audit_alloy_references(alloys, reference)
    }


def test_normative_sources_are_annotated_not_disguised_as_official_full_text():
    source = _read("data/verified_references/alloy_standards.json")
    for s in source["sources"]:
        assert s["url"].startswith("https://protect.gost.ru/")
        assert s["text_url"].startswith("https://")
        assert s["text_kind"] == "third_party_reproduction"
    assert "physical" not in str(source.get("usage_policy", "")).lower()


def test_duplicate_alias_and_unreferenced_standard_rejected():
    reference = {
        "sources": [{"id": "s", "designation": "ГОСТ X", "title": "X",
                     "url": "https://protect.gost.ru/test",
                     "text_url": "https://example.com/x",
                     "text_kind": "third_party_reproduction",
                     "evidence_scope": "section 1"}],
        "grades": [
            {"name": "АК12", "aliases": ["АЛ2"], "category": "aluminum",
             "standard_id": "s", "group": "Al", "evidence": "table 1",
             "verification_status": "verified_designation_only"},
            {"name": "АЛ2", "category": "aluminum", "standard_id": "missing",
             "group": "Al", "evidence": "table 1",
             "verification_status": "verified_designation_only"},
        ],
    }
    errors = validate_grade_index(reference)
    assert any("Повтор обозначения" in e for e in errors)
    assert any("неизвестный ГОСТ" in e for e in errors)


def test_gost_gray_iron_qualifications_and_aluminium_aliases():
    data = _read("data/verified_references/alloy_standards.json")
    grades = {(x["category"], x["name"]): x for x in data["grades"]}
    for name in ("СЧ18", "СЧ21", "СЧ24"):
        assert grades[("cast_iron", name)]["customer_request_only"] is True
    assert grades[("aluminum", "АК9ч")]["aliases"] == ["АЛ4"]
    assert grades[("aluminum", "АК7пч")]["aliases"] == ["АЛ9-1"]
    assert "поправка" in grades[("aluminum", "АК7пч")]["note"].lower()
