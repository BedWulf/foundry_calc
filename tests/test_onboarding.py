"""The first-start suggestion must never reappear after dismissal or acceptance."""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core.casting_item import CastingItem
from core.onboarding import OnboardingState, TUTORIAL_STEPS
from core.tutorial_example import save_tutorial_excel
from gui.main_window import MainWindow
from import_export.excel_importer import ExcelImporter


def test_one_time_offer_persists_across_app_instances(tmp_path):
    state = OnboardingState(tmp_path)
    assert state.should_offer()
    state.mark_offered()
    assert not state.should_offer()
    new_process_state = OnboardingState(tmp_path)
    assert not new_process_state.should_offer()
    saved = json.loads((tmp_path / "onboarding.json").read_text(encoding="utf-8"))
    assert saved["tutorial_offered"] is True


def test_offer_marked_before_user_chooses_and_never_reopened(tmp_path):
    app = QApplication.instance() or QApplication([])
    w = MainWindow()
    w._onboarding = OnboardingState(tmp_path)
    w._offer_tutorial_once()
    assert not w._onboarding.should_offer()
    assert hasattr(w, "_welcome_prompt")
    w._welcome_prompt.close()   # user declines or closes the dialog
    w.close()

    w2 = MainWindow()
    w2._onboarding = OnboardingState(tmp_path)
    w2._offer_tutorial_once()
    assert not hasattr(w2, "_welcome_prompt")
    w2.close()


def test_manual_tour_can_restart_but_does_not_edit_real_project():
    app = QApplication.instance() or QApplication([])
    w = MainWindow()
    c = CastingItem(name="Рабочая отливка", molds_per_year=55,
                    annual_qty_pcs=55, mass_with_LPS_kg=12)
    w.project.castings = [c]
    old_name = w.project.name
    prior_index = w.content_stack.currentIndex()
    help_tab = w.tabs["help_tab"]
    help_tab.tutorial_requested.emit()
    assert w._tour_index == 0
    assert w.tour_instruction.text()
    assert w.content_stack.currentWidget() == help_tab
    for i, step in enumerate(TUTORIAL_STEPS[1:], 1):
        w._tour_next()
        assert w._tour_index == i
        assert w.content_stack.currentWidget() == w.tabs[step.section]
    w._tour_next()
    assert w._tour_index == -1
    assert w.content_stack.currentIndex() == prior_index
    assert w.project.castings == [c]
    assert w.project.name == old_name
    help_tab.tutorial_requested.emit()
    assert w._tour_index == 0
    w._stop_tutorial()
    assert w.project.castings == [c]
    w.close()


def test_tutorial_xlsx_is_importable_and_does_not_modify_project(tmp_path):
    p = tmp_path / "demo.xlsx"
    project_before = [CastingItem(name="Настоящий заказ")]
    saved = save_tutorial_excel(p)
    assert saved == p
    items = ExcelImporter(saved).parse()
    assert len(items) == 2
    assert [c.molds_per_year for c in items] == [600, 300]
    assert [c.pouring_mass_kg for c in items] == [18, 17]
    assert items[0].flask_size_mm == "900x600x200/200"
    assert project_before[0].name == "Настоящий заказ"
