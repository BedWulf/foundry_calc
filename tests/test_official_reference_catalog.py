"""Bundled independent manufacturer references, not machine-inferred values."""
import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.official_reference_catalog import list_official_references


ROOT = Path(__file__).resolve().parents[1] / "data"


def test_bundled_manufacturer_and_gost_records_visible_offline():
    catalog = list_official_references(ROOT)
    assert {name: len(rows) for name, rows in catalog.items()} == {
        "Плавильные печи": 9,
        "Формовочные линии": 7,
        "Стержневые машины": 3,
        "Марки материалов": 96,
    }
    for records in catalog.values():
        for row in records:
            assert row["source"] and row["url"].startswith("https://")
            assert row["conditions"] and row["status"]


def test_sinto_molding_rates_match_published_model_table():
    data = json.loads((ROOT / "verified_references" /
                       "sinto_foundry_equipment.json").read_text(encoding="utf-8"))
    by_model = {x["model"]: x for x in data["molding_lines"]}
    assert {model: info["specs"]["published_molding_rate_molds_h"]
            for model, info in by_model.items()} == {
        "HSP-1": 35, "HSP-2": 25, "HSP-3": 18,
        "HSP-1D": 70, "HSP-2D": 60, "HSP-3D": 50, "HSP-4D": 40,
    }
    assert all(x["eligible_for_final_design"] is False for x in by_model.values())
    # Manufacturer does not publish the maximum poured metal per flask here.
    assert all("max_mold_metal_kg" not in x["specs"] for x in by_model.values())


def test_sinto_core_dry_cycles_are_not_fabricated_hourly_output():
    data = json.loads((ROOT / "verified_references" /
                       "sinto_foundry_equipment.json").read_text(encoding="utf-8"))
    by_model = {x["model"]: x["specs"] for x in data["core_machines"]}
    assert {model: specs["dry_cycle_time_s"] for model, specs in
            by_model.items()} == {"CB10": 13, "CB30": 21, "CB60": 26}
    assert all("hourly_output_cores_h" not in spec for spec in by_model.values())


def test_official_catalog_dialog_initializes_without_network_or_modal_windows():
    from PySide6.QtWidgets import QApplication, QTabWidget
    from gui.dialogs.official_catalog_dialog import OfficialCatalogDialog

    app = QApplication.instance() or QApplication([])
    dialog = OfficialCatalogDialog()
    try:
        assert dialog.findChild(QTabWidget).count() == 4
        assert len(dialog.records["Плавильные печи"]) == 9
        assert len(dialog.records["Марки материалов"]) == 96
        assert dialog.records["Марки материалов"][0]["text_url"].startswith("https://")
        # Search works without network or a blocking modal dialog.
        dialog.search.setText("АЛ9-1")
        from PySide6.QtWidgets import QTextBrowser
        assert "АК7пч" in dialog._browsers["Марки материалов"].toPlainText()
        assert dialog.tabs.tabText(3).endswith("(1/96)")
        dialog.search.setText("")
        assert dialog.tabs.tabText(3).endswith("(96/96)")
    finally:
        dialog.close()


def test_project_material_tab_warns_about_unverified_process_values():
    from PySide6.QtWidgets import QApplication
    from core.project import Project
    from gui.tabs.project_tab import ProjectTab

    app = QApplication.instance() or QApplication([])
    tab = ProjectTab(Project())
    try:
        tab._update_alloy_info("steel_20L")
        assert "не подтверждены" in tab.lbl_alloy_info.text()
        assert "ГОСТ: 96 марок" in tab.btn_official_materials.text()
    finally:
        tab.close()


def test_each_equipment_model_links_its_own_manufacturer_table_row():
    from core.official_reference_catalog import list_official_references
    refs = list_official_references(ROOT)
    for category in ("Плавильные печи", "Формовочные линии", "Стержневые машины"):
        assert all("row" in item["source"] or "column" in item["source"]
                   for item in refs[category])
    indotherm = json.loads(
        (ROOT / "verified_references" / "indotherm_casting_units.json")
        .read_text(encoding="utf-8")
    )
    for row in indotherm["entries"]:
        source = row["source_reference"]
        assert source["url"] == indotherm["source"]["url"]
        assert str(row["capacity_kg"]) in source["location"]
    sinto = json.loads(
        (ROOT / "verified_references" / "sinto_foundry_equipment.json")
        .read_text(encoding="utf-8")
    )
    for row in sinto["molding_lines"] + sinto["core_machines"]:
        source = row["source_reference"]
        assert row["model"] in source["location"]
        assert source["url"] == sinto["sources"][row["source_id"]]["url"]
