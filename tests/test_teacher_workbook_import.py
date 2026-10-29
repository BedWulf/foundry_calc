"""Regression: exact teacher's three-sheet course-workbook layout and values.

Data copied from the supplied 'tablitsy_kursach (1).xlsx' Table 8:
20 positions, physical-flask source values and unrounded spreadsheet forms.
"""
import math

from openpyxl import Workbook
from import_export.excel_importer import ExcelImporter

ROWS = [
    [1,"Полумуфта",6.37,125,84,76,817208,12,68100.66666666667,76.44,5205614.96,0.127,8735.272513333335],
    [2,"Щит",4.55,112,63,85,1193128,16,74570.5,72.8,5428732.4,0.127,9565.158035],
    [3,"Кронштейн",13.26,110,73,67,428797,14,30628.35714285714,185.64,5685848.22,0.13,4021.503292857143],
    [4,"Втулка",9.62,92,87,80,319644,12,26637,115.44,3074975.28,0.13,3497.4381],
    [5,"Корпус редуктора",5.85,124,91,60,259424,12,21618.666666666668,70.2,1517630.4,0.13,2838.5309333333335],
    [6,"Траверса",14.69,125,80,98,305877,10,30587.7,146.9,4493333.13,0.127,3923.484279],
    [7,"Корпус насоса",11.44,88,86,80,273673,14,19548.071428571428,160.16,3130819.12,0.129,2546.9182264285714],
    [8,"Патрубок",13,132,76,80,238636,12,19886.333333333332,156,3102268,0.128,2570.905173333333],
    [9,"Крышка задняя",13.26,99,88,80,429563,12,35796.916666666664,159.12,5696005.38,0.129,4663.9802725],
    [10,"Стояк",17.03,115,94,79,273539,10,27353.9,170.3,4658369.17,0.129,3563.939631],
    [11,"Крышка ",14.56,55,115,64,221506,20,11075.3,291.2,3225127.36,0.129,1443.000837],
    [12,"Фланец",12.09,120,44,136,267991,12,22332.583333333332,145.08,3240011.19,0.129,2909.7122825],
    [13,"Золотник",6.37,80,92,100,427597,10,42759.7,63.7,2723792.89,0.13,5614.34861],
    [14,"Плита",13.26,135,84,85,242063,10,24206.3,132.6,3209755.38,0.127,3104.942101],
    [15,"Основание",9.62,91,87,68,291394,14,20813.85714285714,134.68,2803210.28,0.128,2690.815451428571],
    [16,"Штуцер",7.41,123,76,80,411292,12,34274.333333333336,88.92,3047673.72,0.129,4465.60289],
    [17,"Кольцо",12.35,114,84,87,365139,10,36513.9,123.5,4509466.65,0.128,4720.516992],
    [18,"Фланец",13.65,124,64,82,423091,14,30220.785714285714,191.1,5775192.15,0.129,3937.466170714286],
    [19,"Сердечник",10.79,120,92,90,402174,8,50271.75,86.32,4339457.46,0.129,6549.9063075],
    [20,"Диск",3.51,130,85,77,1409545,10,140954.5,35.1,4947502.95,0.128,18222.59776],
]


def workbook(tmp_path):
    wb = Workbook()
    s1 = wb.active
    s1.title = "Таблица 1"
    s1["A1"] = "Наименование  отливок"
    s1["B1"] = "№ отливок"
    s2 = wb.create_sheet("Таблица 2")
    s2["A1"] = "Наименование отливок"
    s2["B1"] = "№ отливок"
    ws = wb.create_sheet("Таблица 8")
    for col, val in {
        1: "Номер", 2: "Наименование отливок",
        3: "Масса, кг",
        7: "Количество отливок с учетом брака, шт.",
        8: "Количество отливок в форме",
        9: "Годовое количество форм с учетом брака, шт",
        10: "Размеры опок, мм",
        12: "Заливочная масса, кг",
        13: "Масса заливаемого металла в год, кг",
    }.items():
        ws.cell(1, col, val)
    ws["D4"] = "длина"
    ws["E4"] = "ширина"
    ws["F4"] = "высота"
    ws["J4"] = "Длина, ширина"
    ws["K4"] = "Высота"
    last = None
    for ix, (number, name, mass, length, width, height, pieces, per,
             source_forms, pour, annual_metal, mix_one, mix_year) in enumerate(ROWS, 7):
        machine = "Автоматическая формовочная линия мод. ИЛ-225" if ix == 7 else None
        row = [number, name, mass, length, width, height, pieces, per,
               source_forms, "900х600", "125/125", pour, annual_metal,
               mix_one, mix_year, machine]
        for col, value in enumerate(row, 1):
            ws.cell(ix, col, value)
    ws["B27"] = "Итого"
    ws["G27"] = 9001281
    ws["M27"] = 79814786.09
    ws["O27"] = 99586.03985892858
    path = tmp_path / "course_teacher.xlsx"
    wb.save(path)
    return path


def test_teacher_workbook_imports_20_unchanged_source_positions(tmp_path):
    preview = ExcelImporter().load_preview(workbook(tmp_path))
    cs = preview.castings
    assert len(cs) == 20
    assert sum(c.annual_qty_with_brak for c in cs) == 9001281
    assert sum(c.molds_per_year for c in cs) == 768159
    assert [c.name for c in cs[:3]] == ["Полумуфта", "Щит", "Кронштейн"]
    assert all(c.flask_size_mm == "900x600x125/125" for c in cs)
    assert all(c.molding_machine == "Автоматическая формовочная линия мод. ИЛ-225" for c in cs)
    assert cs[0].annual_metal_t == 68101 * 76.44 / 1000
    assert math.isclose(sum(c.annual_metal_t for c in cs),
                        79815.86496, abs_tol=1e-4)
    assert any("Таблица 8" in w for w in preview.warnings)
    assert any("ceil(" in w for w in preview.warnings)


def test_normal_A_P_template_still_imports(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.append(["Поля"])
    ws.append(["Заполните"])
    ws.append(["№", "Наименование", "Масса с ЛПС", None,None,None,None,
               "Масса, т"])
    ws.append([1, "Корпус", 10, "120x80", 60, 1000, 2, None,
               900, 600, "125/125", 25, None, .12, None, "ИЛ-225"])
    path = tmp_path / "normal.xlsx"
    wb.save(path)
    preview = ExcelImporter().load_preview(path)
    assert len(preview.castings) == 1
    assert preview.castings[0].molds_per_year == 500
