"""Per-casting source evidence is not a global yes/no declaration."""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from core.casting_audit import audit_casting_technology
from core.casting_item import CastingItem
from core.core_making import core_counts_complete
from core.project import Project
from core.project_io import ProjectFileError, read_project, write_project
from core.summary import build_summary
from gui.dialogs.casting_technology_dialog import CastingTechnologyDialog
from gui.tabs.project_tab import ProjectTab


def app():
    return QApplication.instance() or QApplication([])


def rows():
    return [
        CastingItem(
            name="Без стержней", molds_per_year=300,
            cores_count=0, mass_with_LPS_kg=8,
            mass_casting_kg=0,
        ),
        CastingItem(
            name="Стержневая", molds_per_year=100,
            cores_count=2, mass_with_LPS_kg=10,
            mass_casting_kg=9,
        ),
    ]


def test_verified_zero_on_single_row_does_not_confirm_another_zero():
    items = rows()
    items.append(CastingItem(name="Вторая пустая", molds_per_year=50, cores_count=0))
    assert not core_counts_complete(items)
    items[0].cores_count_verified = True
    items[0].cores_count_source = "Техкарта 7/А"
    assert not core_counts_complete(items)
    items[2].cores_count_verified = True
    items[2].cores_count_source = "Чертёж №42"
    assert core_counts_complete(items)


def test_legacy_confirmation_still_works_for_old_projects():
    assert core_counts_complete(rows(), zeros_confirmed=True)


def test_technical_source_audit_distinguishes_missing_and_verified_values():
    items = rows()
    issues = audit_casting_technology(items)
    codes = {i.code for i in issues}
    assert "core_source_missing" in codes
    assert "clean_mass_missing" in codes
    assert "clean_mass_source_missing" in codes
    items[0].cores_count_verified = True
    items[0].cores_count_source = "Технологическая карта 8"
    items[0].mass_casting_kg = 7
    items[0].mass_casting_verified = True
    items[0].mass_casting_source = "Чертёж 8"
    items[1].cores_count_verified = True
    items[1].cores_count_source = "Технологическая карта 9"
    items[1].mass_casting_verified = True
    items[1].mass_casting_source = "Чертёж 9"
    assert audit_casting_technology(items) == []


def test_pure_casting_mass_cannot_exceed_mass_with_lps():
    c = CastingItem(name="Нарушение", molds_per_year=1, mass_with_LPS_kg=10,
                    mass_casting_kg=12, mass_casting_verified=True,
                    mass_casting_source="Технологическая карта")
    assert any(x.code == "clean_mass_over_lps"
               for x in audit_casting_technology([c]))


@pytest.mark.parametrize("kwargs", [
    {"cores_count_verified": True, "cores_count_source": ""},
    {"mass_casting_verified": True, "mass_casting_kg": 0,
     "mass_casting_source": "Чертёж"},
    {"mass_casting_verified": True, "mass_casting_kg": 7,
     "mass_casting_source": ""},
    {"cores_count_source": "x" * 2049},
])
def test_unjustified_verification_does_not_overwrite_saved_project(
    tmp_path, kwargs
):
    target = tmp_path / "casting.fpro.json"
    write_project(target, Project(castings=rows()))
    safe_bytes = target.read_bytes()
    cast = rows()[0]
    for field, value in kwargs.items():
        setattr(cast, field, value)
    with pytest.raises(ProjectFileError):
        write_project(target, Project(castings=[cast]))
    assert target.read_bytes() == safe_bytes


def test_evidence_survives_save_and_old_files_remain_unverified(tmp_path):
    source = rows()[0]
    source.cores_count_verified = True
    source.cores_count_source = "Технологическая карта 8"
    source.mass_casting_kg = 7
    source.mass_casting_verified = True
    source.mass_casting_source = "Чертёж №1"
    p = Project(castings=[source])
    path = tmp_path / "source.fpro.json"
    write_project(path, p)
    loaded = read_project(path).project.castings[0]
    assert loaded.cores_count_verified and loaded.mass_casting_verified
    assert loaded.cores_count_source == "Технологическая карта 8"
    assert loaded.mass_casting_source == "Чертёж №1"
    old = json.loads(path.read_text(encoding="utf-8"))
    for key in (
        "cores_count_verified", "cores_count_source",
        "mass_casting_verified", "mass_casting_source",
    ):
        old["project"]["castings"][0].pop(key)
    path.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
    legacy = read_project(path).project.castings[0]
    assert not legacy.cores_count_verified
    assert not legacy.mass_casting_verified
    assert audit_casting_technology([legacy])


def test_dialog_edit_updates_only_selected_casting_after_accept():
    app()
    project = Project(castings=rows(), cores_zero_confirmed=True)
    tab = ProjectTab(project)
    original_other = project.castings[1]
    tab.table.selectRow(0)
    dialog = CastingTechnologyDialog(project.castings[0], tab)
    dialog.cores_count_source.setText("Техкарта 1")
    dialog.cores_verified.setChecked(True)
    dialog.clean_mass.setValue(7)
    dialog.clean_mass_source.setText("Чертёж 1")
    dialog.mass_verified.setChecked(True)
    dialog._save()
    assert dialog.result_item is not None
    # Simulate user accepting the modal by swapping the one selected row.
    project.castings[0] = dialog.result_item
    project.cores_zero_confirmed = False
    assert core_counts_complete(project.castings)
    assert project.castings[1] is original_other
    assert audit_casting_technology([project.castings[0]]) == []
    tab.close()


def test_unverified_evidence_is_visible_in_project_summary():
    p = Project(castings=rows())
    result = build_summary({}, p)
    assert result.ready is False
    assert any("источникам технологических данных" in warning
               for warning in result.warnings)
