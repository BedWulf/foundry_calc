"""First-run Excel import must match the public CastingItem API."""
from pathlib import Path
from openpyxl import Workbook
from import_export.excel_importer import ExcelImporter
from core.project import Project


def workbook(tmp_path: Path, *, in_mold=2, quantity=1001, pouring=23,
             flask="200/250"):
    wb = Workbook()
    ws = wb.active
    ws.append(["Подготовка", "Номенклатура"])
    ws.append(["Поля A-P"])
    ws.append(["№", "Наименование"])
    row = [1, "Корпус", 10, "130x150", 60, quantity, in_mold,
           None, 900, 600, flask, pouring, None, 0.2, None, "ИЛ-225"]
    ws.append(row)
    path = tmp_path / "nomenclature.xlsx"
    wb.save(path)
    return path


def test_first_launch_excel_import_uses_correct_field_names(tmp_path):
    path = workbook(tmp_path)
    imp = ExcelImporter(path)
    items = imp.parse()
    assert len(items) == 1
    c = items[0]
    assert c.annual_qty_with_brak == 1001
    assert c.molds_per_year == 501  # 1001 castings / 2 per mold
    assert c.pouring_mass_kg == 23
    assert c.annual_metal_t == 501 * 23 / 1000
    assert c.flask_size_mm == "900x600x200/250"
    assert c.mass_with_LPS_kg == 10
    p = Project()
    p.add_casting(c)
    assert abs(p.total_castings_mass_t() - c.annual_metal_t) < 1e-12


def test_preview_import_project_does_not_need_legacy_recalc_totals(tmp_path):
    imp = ExcelImporter()
    prev = imp.load_preview(workbook(tmp_path))
    p = Project()
    imp.apply_to_project(prev, p)
    assert p.castings[0].molds_per_year == 501


def test_missing_pour_mass_warns_and_explicitly_estimates(tmp_path):
    imp = ExcelImporter()
    prev = imp.load_preview(workbook(tmp_path, pouring=None))
    assert prev.castings[0].pouring_mass_kg == 20
    assert any("заливочная масса оценена" in warning for warning in prev.warnings)


def test_invalid_row_is_rejected(tmp_path):
    imp = ExcelImporter()
    path = workbook(tmp_path, quantity=0)
    try:
        imp.load_preview(path)
        assert False, "EmptyDataError expected"
    except Exception as exc:
        assert "корректной записи" in str(exc)


def test_gui_import_entrypoint_exists(tmp_path):
    assert hasattr(ExcelImporter(workbook(tmp_path)), "parse")
