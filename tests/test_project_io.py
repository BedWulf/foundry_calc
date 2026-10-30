"""Full-project portable storage regression tests. JSON, no pickle."""
import json
from datetime import date

import pytest

from core.project import Project
from core.casting_item import CastingItem
from core.project_io import (
    ProjectFileError, FILE_EXTENSION, read_project, write_project,
    project_inputs, plan_custom_catalog_restore, restore_custom_catalogs,
)


def populated():
    p = Project(
        name="Дипломный выпуск",
        project_uid="demo-uuid-unique",
        created_at=date(2026, 10, 30),
        customer="Учебный завод",
        annual_output_t=37000,
        alloy="20Л",
        shifts_per_day=3, shift_duration_h=7.5,
        molding_batches_per_year=8, molding_setup_h=2.25,
        molding_max_load_factor=.73,
        molding_park_mode="manual",
        molding_line_counts={"IL-225": 3, "line2": 1},
        molding_peak_concurrent_lines=2,
    )
    p.castings = [
        CastingItem(index=1, name="Корпус", annual_qty_pcs=1200,
                    annual_qty_with_brak=1260, mass_with_LPS_kg=8.4,
                    molds_per_year=630, pouring_mass_kg=20,
                    annual_metal_t=12.6, flask_size_mm="900x600x200/200",
                    core_machine="STM", core_volume_m3=.12),
        CastingItem(index=2, name="Крышка", annual_qty_pcs=2000,
                    molds_per_year=1000, pouring_mass_kg=13,
                    annual_metal_t=13.0, drawing="123-456"),
    ]
    return p


def test_all_castings_and_manual_fleet_roundtrip(tmp_path):
    p = populated()
    choices = {
        "melting_furnace": {"equipment_id": "ID-6"},
        "molding_line": {"equipment_id": "IL-225"},
        "cleaning_equipment": {
            "shot_blasting": {"equipment_id": "cleaning-A"},
        },
    }
    catalogs = {"custom_furnaces.json": {
        "version": "1.0",
        "furnaces": [{"id": "my-6", "name": "Печь пользователя"}],
    }}
    path = tmp_path / ("my-castings" + FILE_EXTENSION)
    write_project(path, p, choices, catalogs)
    loaded = read_project(path)
    assert project_inputs(loaded.project) == project_inputs(p)
    assert loaded.project.project_id == p.project_id
    assert loaded.project.created_at == date(2026, 10, 30)
    assert loaded.project.molding_line_counts == {"IL-225": 3, "line2": 1}
    assert loaded.project.molding_peak_concurrent_lines == 2
    assert loaded.project.castings[0].cores_count == 0
    assert loaded.project.castings[1].drawing == "123-456"
    assert loaded.choices == choices
    assert loaded.custom_catalogs == catalogs
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 1


def test_derived_values_are_not_imported_as_engineering_results(tmp_path):
    p = populated()
    p.metal_charge_t = 777777.0
    p.F_equipment_h = 27
    file = tmp_path / "p.fpro.json"
    write_project(file, p)
    result = read_project(file).project
    assert result.metal_charge_t == 0
    assert result.F_equipment_h == Project().F_equipment_h
    assert result.castings[0].annual_metal_t == 12.6


@pytest.mark.parametrize("mutation", [
    lambda d: d.update({"format": "dangerous-other"}),
    lambda d: d.update({"version": 99}),
    lambda d: d["project"].update({"created_at": "yesterday"}),
    lambda d: d["project"].update({"molding_park_mode": "unknown"}),
    lambda d: d["project"].update({"molding_line_counts": {"bad": -1}}),
    lambda d: d["project"]["castings"][0].update({"unexpected": "field"}),
    lambda d: d["project"]["castings"][0].update({"molds_per_year": -20}),
])
def test_reject_corrupt_or_unknown_project(tmp_path, mutation):
    path = tmp_path / "wrong.fpro.json"
    write_project(path, populated())
    document = json.loads(path.read_text(encoding="utf-8"))
    mutation(document)
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ProjectFileError):
        read_project(path)


def test_atomic_save_does_not_damage_previous_file_on_validation_error(tmp_path):
    path = tmp_path / "data.fpro.json"
    good = populated()
    write_project(path, good)
    first = path.read_bytes()
    bad = populated()
    bad.annual_output_t = float("nan")
    with pytest.raises(ProjectFileError):
        write_project(path, bad)
    assert path.read_bytes() == first


def test_custom_equipment_merge_preserves_existing_and_conflict_is_rejected(tmp_path):
    catalog = tmp_path / "custom_furnaces.json"
    catalog.write_text(json.dumps({
        "version": "1.0", "furnaces": [
            {"id": "local", "name": "Местная печь"},
        ],
    }), encoding="utf-8")
    incoming = {"custom_furnaces.json": {
        "version": "1.0", "furnaces": [
            {"id": "from-project", "name": "Печь из проекта"},
        ],
    }}
    pending = plan_custom_catalog_restore(tmp_path, incoming)
    restore_custom_catalogs(pending)
    result = json.loads(catalog.read_text(encoding="utf-8"))
    assert [x["id"] for x in result["furnaces"]] == ["local", "from-project"]
    incoming["custom_furnaces.json"]["furnaces"] = [
        {"id": "local", "name": "Другая печь"}
    ]
    with pytest.raises(ProjectFileError):
        plan_custom_catalog_restore(tmp_path, incoming)
    assert json.loads(catalog.read_text(encoding="utf-8")) == result
