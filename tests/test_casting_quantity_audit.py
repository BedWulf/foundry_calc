"""Engineering checks of piece/mold multiplicity and pour-metal conservation."""
import json

import pytest

from core.casting_audit import audit_castings
from core.casting_item import CastingItem
from core.project import Project
from core.project_io import ProjectFileError, read_project, write_project
from core.summary import build_summary
from import_export.excel_importer import ExcelImporter
from tests.test_excel_onboarding import workbook


def valid_casting(**changes):
    values = dict(
        name="Корпус", mass_with_LPS_kg=10,
        annual_qty_pcs=1001, annual_qty_with_brak=1001,
        castings_per_mold=2, molds_per_year=501,
        pouring_mass_kg=23, annual_metal_t=501 * 23 / 1000,
    )
    values.update(changes)
    return CastingItem(**values)


def test_consistent_physical_casting_program_has_no_issues():
    assert audit_castings([valid_casting()]) == []


def test_missing_multiplicity_is_unknown_not_assumed_one():
    problems = audit_castings([valid_casting(castings_per_mold=0)])
    assert any(p.code == "no_multiplicity" and p.severity == "unverified"
               for p in problems)
    assert all(p.code != "mold_count" for p in problems)


def test_mold_count_uses_ceiling_not_fractional_mold():
    bad = valid_casting(molds_per_year=500)
    problems = audit_castings([bad])
    assert any(p.code == "mold_count" and p.severity == "inconsistent"
               for p in problems)


def test_mass_per_mold_checks_pieces_times_lps_mass():
    wrong = valid_casting(pouring_mass_kg=15, annual_metal_t=501 * 15 / 1000)
    issues = audit_castings([wrong])
    assert any(p.code == "mass_per_mold" for p in issues)
    assert not any(p.code == "annual_mass" for p in issues)


def test_annual_metal_balance_detects_independent_disagreement():
    wrong = valid_casting(annual_metal_t=14)
    issues = audit_castings([wrong])
    assert any(p.code == "annual_mass" for p in issues)


def test_estimated_pour_mass_never_counts_as_verified_source():
    issues = audit_castings([valid_casting(pouring_mass_estimated=True)])
    assert any(p.code == "estimated_pour_mass" and p.severity == "unverified"
               for p in issues)


def test_import_persists_castings_per_mold_and_reports_bad_lps_mass(tmp_path):
    c = ExcelImporter().load_preview(workbook(tmp_path))
    assert c.castings[0].castings_per_mold == 2
    assert c.castings[0].pouring_mass_estimated is False
    assert audit_castings(c.castings) == []
    c2 = ExcelImporter().load_preview(workbook(tmp_path, pouring=15))
    assert any("меньше C×G" in w for w in c2.warnings)
    assert any(i.code == "mass_per_mold" for i in audit_castings(c2.castings))


def test_source_missing_pour_mass_remains_unverified_after_import(tmp_path):
    p = ExcelImporter().load_preview(workbook(tmp_path, pouring=None))
    assert p.castings[0].pouring_mass_estimated
    assert p.castings[0].castings_per_mold == 2
    assert any(i.code == "estimated_pour_mass" for i in audit_castings(p.castings))


def test_import_rejects_blank_multiplicity_instead_of_assuming_one(tmp_path):
    from import_export.excel_importer import EmptyDataError
    with pytest.raises(EmptyDataError):
        ExcelImporter().load_preview(workbook(tmp_path, in_mold=None))


def test_audit_prevents_summary_being_marked_fully_ready():
    p = Project(castings=[valid_casting(annual_metal_t=99)])
    res = build_summary({}, p)
    assert not res.ready
    assert any("НЕ ПОДТВЕРЖДЕНА НОМЕНКЛАТУРА" in w for w in res.warnings)
    assert any("не согласуется" in w for w in res.warnings)


def test_casting_multiplicity_and_estimation_provenance_survive_project_roundtrip(tmp_path):
    p = Project(castings=[valid_casting(pouring_mass_estimated=True)])
    file = tmp_path / "castings.fpro.json"
    write_project(file, p)
    loaded = read_project(file).project
    assert loaded.castings[0].castings_per_mold == 2
    assert loaded.castings[0].pouring_mass_estimated


def test_old_project_has_unknown_multiplicity_without_rewriting_source(tmp_path):
    f = tmp_path / "legacy.fpro.json"
    write_project(f, Project(castings=[valid_casting()]))
    old = json.loads(f.read_text(encoding="utf-8"))
    old["project"]["castings"][0].pop("castings_per_mold")
    old["project"]["castings"][0].pop("pouring_mass_estimated")
    f.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
    c = read_project(f).project.castings[0]
    assert c.castings_per_mold == 0
    assert any(i.code == "no_multiplicity" for i in audit_castings([c]))


@pytest.mark.parametrize("changes", [
    {"castings_per_mold": -1},
    {"annual_qty_with_brak": -2},
    {"annual_qty_pcs": -4},
    {"mass_with_LPS_kg": -2},
    {"pouring_mass_kg": -1},
    {"annual_metal_t": -10},
])
def test_bad_casting_cannot_overwrite_saved_project(tmp_path, changes):
    path = tmp_path / "good.fpro.json"
    write_project(path, Project(castings=[valid_casting()]))
    original = path.read_bytes()
    with pytest.raises(ProjectFileError):
        write_project(path, Project(castings=[valid_casting(**changes)]))
    assert path.read_bytes() == original



def test_capacity_summary_tolerates_placeholder_casting_program():
    from types import SimpleNamespace
    placeholder = SimpleNamespace(name="Чужой клиент", annual_output_t=100,
                                  castings=[object()])
    result = build_summary({}, placeholder)
    assert result.project_name == "Чужой клиент"
    # Data-quality auditing does not assume a placeholder is a CastingItem.
    assert not any("НЕ ПОДТВЕРЖДЕНА НОМЕНКЛАТУРА" in x
                   for x in result.warnings)



def test_large_casting_browser_shows_multiplicity_and_row_issues():
    from PySide6.QtCore import Qt
    from gui.dialogs.castings_browser import CastingsTableModel

    model = CastingsTableModel([
        valid_casting(),
        valid_casting(annual_metal_t=99),
        valid_casting(castings_per_mold=0),
    ])
    assert model.columnCount() == 10
    assert model.headerData(5, Qt.Horizontal, Qt.DisplayRole) == "Отливок/форму"
    assert model.data(model.index(0, 5), Qt.DisplayRole) == "2"
    assert model.data(model.index(2, 5), Qt.DisplayRole) == "неизвестно"
    assert model.data(model.index(0, 9), Qt.DisplayRole) == "✓"
    assert "⚠" in model.data(model.index(1, 9), Qt.DisplayRole)
    assert "не согласуется" in model.data(model.index(1, 9), Qt.ToolTipRole)
