"""Proof that questionable catalogue entries are rejected, not fabricated."""
from core.verified_equipment_gate import verify_equipment_for_selection


REQUIRED = {"capacity_t": "t", "productivity_t_h": "t/h"}


def test_legacy_record_cannot_pass_as_verified():
    legacy = {"id": "IST-6M1", "specs": {
        "capacity_t": 6.0, "productivity_t_h": 3.0}}
    assert verify_equipment_for_selection(legacy, REQUIRED)


def test_sourced_values_without_conditions_are_not_eligible():
    source = {"source_type": "manufacturer_datasheet",
              "document_url": "https://example.com/datasheet",
              "document_title": "Equipment datasheet", "document_revision": "A",
              "location": "table 2", "model_designation": "M1"}
    def value(n, unit):
        return {"value": n, "unit": unit, "source": source, "conditions": {},
                "verification_status": "verified"}
    machine = {"model_designation": "M1", "verified_parameters": {
        "capacity_t": value(2, "t"),
        "productivity_t_h": value(1, "t/h")}}
    assert verify_equipment_for_selection(machine, REQUIRED)


def test_other_model_datasheet_is_rejected():
    source = {"source_type": "manufacturer_datasheet",
              "document_url": "https://example.com/datasheet",
              "document_title": "Equipment datasheet", "document_revision": "A",
              "location": "table 2", "model_designation": "M2"}
    machine = {"model_designation": "M1", "verified_parameters": {
        field: {"value": 1, "unit": unit, "source": source,
                "conditions": {"steel_temperature_c": 1650},
                "verification_status": "verified"}
        for field, unit in REQUIRED.items()}}
    assert any("другой модификации" in reason for reason in
               verify_equipment_for_selection(machine, REQUIRED))


def test_complete_individual_sources_pass_structural_gate_only():
    model = "M1"
    source = {"source_type": "manufacturer_datasheet",
              "document_url": "https://example.com/datasheet",
              "document_title": "Equipment datasheet", "document_revision": "A",
              "location": "table 2", "model_designation": model}
    machine = {"model_designation": model, "verified_parameters": {
        field: {"value": 1, "unit": unit, "source": source,
                "conditions": {"specified_test_temperature_c": 1650},
                "verification_status": "verified"}
        for field, unit in REQUIRED.items()}}
    assert verify_equipment_for_selection(machine, REQUIRED) == []
    # Structural pass is NOT proof that example.com is genuine or operating
    # throughput applies to a particular casting process.
