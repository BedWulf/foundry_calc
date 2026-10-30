"""Geometry and conservation checks independent of diploma expected outputs."""
import json

import pytest

from core.casting_item import CastingItem
from core.project import Project
from core.project_io import ProjectFileError, read_project, write_project
from core.sand_prep import calc_sand_prep, calc_sand_volumes


def test_metal_displacement_is_mass_divided_by_selected_density():
    # 270 kg fills 0.1 m³ at 2700 kg/m³; it fills only 0.034615...
    # m³ if incorrectly treated as steel (7800 kg/m³).
    aluminum = calc_sand_volumes(
        100, 1.0, 270, 0, metal_density_t_m3=2.7)
    steel = calc_sand_volumes(
        100, 1.0, 270, 0, metal_density_t_m3=7.8)
    assert aluminum["sand_volume_tamped_m3"] == 90.0
    assert steel["sand_volume_tamped_m3"] == pytest.approx(96.5, abs=0.05)
    assert aluminum["sand_volume_tamped_m3"] < steel["sand_volume_tamped_m3"]


def test_project_alloy_density_controls_molding_sand_volume():
    project = Project()
    project.castings = [CastingItem(
        name="Geometry check", molds_per_year=100,
        mass_with_LPS_kg=270,
        flask_size_mm="1000x1000x500/500",
        cores_count=0,
    )]
    project.selected_alloy_id = "aluminum_AK12"
    project.alloy_density_kg_m3 = 2700
    first = calc_sand_prep(project)
    assert first["volumes"]["sand_volume_tamped_m3"] == 90.0
    project.alloy_density_kg_m3 = 7800
    second = calc_sand_prep(project)
    assert second["volumes"]["sand_volume_tamped_m3"] == pytest.approx(96.5, abs=.05)
    # The same geometry with different density affects sand-preparation
    # demand and must not silently retain the steel-only result.
    assert first["volumes"]["sand_volume_loose_m3"] < second["volumes"]["sand_volume_loose_m3"]


@pytest.mark.parametrize("bad_density", [0, -1, float("nan"), float("inf")])
def test_nonphysical_density_cannot_be_used_for_metal_volume(bad_density):
    with pytest.raises(ValueError):
        calc_sand_volumes(
            annual_molds=100, mold_volume_m3=1.0,
            metal_per_mold_kg=50, cores_mass_per_mold_kg=0,
            metal_density_t_m3=bad_density)


@pytest.mark.parametrize("bad_density", [0, -50, float("nan"), float("inf")])
def test_project_with_nonphysical_density_not_saved(tmp_path, bad_density):
    saved = tmp_path / "good.fpro.json"
    project = Project()
    write_project(saved, project)
    original = saved.read_bytes()
    project.alloy_density_kg_m3 = bad_density
    with pytest.raises(ProjectFileError):
        write_project(saved, project)
    assert saved.read_bytes() == original


def test_project_with_nonphysical_density_not_loaded(tmp_path):
    saved = tmp_path / "bad.fpro.json"
    write_project(saved, Project())
    document = json.loads(saved.read_text(encoding="utf-8"))
    document["project"]["alloy_density_kg_m3"] = -1
    saved.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ProjectFileError):
        read_project(saved)


def test_direct_department_call_can_use_explicit_material_density():
    from core.sand_prep import SandPrepCalculator
    calc = SandPrepCalculator()
    steel = calc.calc_department(
        annual_output_t=20, annual_molds=100, mold_volume_m3=1.0,
        metal_per_mold_kg=270, cores_per_mold=0, metal_density_t_m3=7.8)
    aluminum = calc.calc_department(
        annual_output_t=20, annual_molds=100, mold_volume_m3=1.0,
        metal_per_mold_kg=270, cores_per_mold=0, metal_density_t_m3=2.7)
    assert steel["volumes"]["sand_volume_tamped_m3"] == pytest.approx(96.5, abs=.05)
    assert aluminum["volumes"]["sand_volume_tamped_m3"] == 90.0
