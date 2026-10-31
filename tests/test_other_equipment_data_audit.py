"""Regression checks for suspicious, but not automatically 'corrected', data."""
import json
from pathlib import Path

import pytest

from core.other_equipment_data_audit import audit_equipment_catalog


ROOT = Path(__file__).resolve().parents[1] / "data" / "equipment"


@pytest.mark.parametrize("filename,kind", [
    ("furnaces.json", "furnaces"),
    ("core_machines.json", "core_machines"),
    ("mixers.json", "mixers"),
])
def test_catalog_structure_and_units(filename, kind):
    data = json.loads((ROOT / filename).read_text(encoding="utf-8"))
    issues = audit_equipment_catalog(data, kind)
    forbidden = {"INVALID_CATALOG", "INVALID_ITEM", "MISSING_ID", "DUPLICATE_ID",
                 "MISSING_SPECS", "INVALID_SPEC", "INVALID_UNIT", "INVALID_RANGE"}
    assert not [i for i in issues if i["code"] in forbidden]


def test_core_cycle_mismatch_is_reported_not_silently_replaced():
    data = json.loads((ROOT / "core_machines.json").read_text(encoding="utf-8"))
    issues = audit_equipment_catalog(data, "core_machines")
    assert any(i["equipment_id"] == "ZB08Y-80" and
               i["code"] == "CORE_RATE_MISMATCH" for i in issues)
    entry = next(x for x in data["machines"] if x["id"] == "ZB08Y-80")
    assert entry["specs"]["hourly_output_cores_h"] == 576


def test_boolean_and_nan_values_are_invalid():
    data = {"furnaces": [{"id": "test", "specs": {
        "capacity_t": True, "productivity_t_h": float("nan"),
        "melt_time_h": 1, "power_kw": 0,
    }}]}
    issues = audit_equipment_catalog(data, "furnaces")
    assert sum(x["code"] == "INVALID_SPEC" for x in issues) == 2


def test_continuous_cupola_is_not_checked_with_batch_cycle_ceiling():
    """A cupola throughput must not be bounded by batch crucible logic."""
    data = {"furnaces": [{
        "id": "continuous", "type": "cupola_water_cooled",
        "specs": {"capacity_t": 1.5, "productivity_t_h": 4.0,
                  "melt_time_h": 0.5, "power_kw": 0},
    }]}
    issues = audit_equipment_catalog(data, "furnaces")
    assert "RATE_EXCEEDS_SIMPLE_CYCLE" not in {i["code"] for i in issues}


def test_batch_furnace_inconsistent_cycle_still_warns():
    data = {"furnaces": [{
        "id": "batch", "type": "induction_crucible",
        "specs": {"capacity_t": 1.0, "productivity_t_h": 1.0,
                  "melt_time_h": 2.0, "power_kw": 500},
    }]}
    issues = audit_equipment_catalog(data, "furnaces")
    assert "RATE_EXCEEDS_SIMPLE_CYCLE" in {i["code"] for i in issues}
