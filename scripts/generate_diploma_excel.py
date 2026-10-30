#!/usr/bin/env python3
"""Regenerate 2 XLSX fixtures DIRECTLY from the repository diploma PDFs.

No invented casting rows: the source of truth is the tables printed on
PDF page 27 / PDF page 25. Every numeric field is extracted; checks compare
source rows and printed totals without silently replacing either.
"""
from __future__ import annotations

import math
import re
import subprocess
import tempfile
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "examples"
NAMES2 = [
    "Полумуфта", "Щит", "Кронштейн", "Втулка", "Корпус редуктора",
    "Траверса", "Корпус насоса", "Патрубок", "Крышка задняя", "Стояк",
    "Крышка", "Фланец", "Золотник", "Плита", "Основание", "Штуцер",
    "Кольцо", "Фланец", "Сердечник", "Диск",
]


def pdf_text(filename: str) -> str:
    with tempfile.TemporaryDirectory() as td:
        temp_file = Path(td) / "source.txt"
        subprocess.run(
            ["pdftotext", "-layout", str(ROOT / filename), str(temp_file)],
            check=True,
        )
        return temp_file.read_text(encoding="utf-8")


def extract_1() -> list[dict]:
    t = pdf_text("Sample Diploma.pdf")
    a = t[t.index("Таблица 9. Ведомость формовки."):]
    a = a[:a.index("В условиях крупносерийного и массового производства")]
    rows = []
    for line in a.splitlines():
        v = line.split()
        if len(v) < 14 or not v[0].isdigit() or not (1 <= int(v[0]) <= 20):
            continue
        if not re.fullmatch(r"\d+[.]\d+", v[2]):
            continue
        if "х" not in v[8] or "/" not in v[9]:
            continue
        rows.append({
            "n": int(v[0]), "name": v[1], "mass": float(v[2]),
            "dimensions": v[3], "height": int(v[4]), "qty": int(v[5]),
            "per": int(v[6]), "molds": int(v[7]),
            "flask": v[8].replace("х", "x"), "flask_height": v[9],
            "pour": float(v[10]), "metal_source": float(v[11]),
            "mix_one": float(v[12]), "mix_year": float(v[13]),
            "machine": "ИЛ-225",
        })
    if len(rows) != 20 or [x["n"] for x in rows] != list(range(1, 21)):
        raise ValueError("Diploma 1 must contain exactly 20 sequential castings")
    return rows


def extract_2() -> list[dict]:
    t = pdf_text("Sample Diploma 2.pdf")
    a = t[t.index("Таблица 8. Ведомость формовки"):]
    a = a[:a.index("В условиях крупносерийного и массового производства")]
    pattern = re.compile(
        r"^\s+(?:([А-ЯЁа-яё]+)\s+)?(\d+(?:,\d+)?)\s+(\d+)\s+(\d+)\s+"
        r"(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(900х600)\s+(\d+/\d+)"
        r"\s+([\d,]+)(?:\s+([\d,]+)\s+([\d,]+)\s+([\d,]+))?\s*$"
    )
    lines = a.splitlines()
    rows = []
    for lineno, line in enumerate(lines):
        m = pattern.match(line)
        if not m:
            continue
        if len(rows) >= len(NAMES2):
            break
        v = m.groups()
        name = NAMES2[len(rows)]
        if v[0] and v[0] != name:
            raise ValueError(f"Wrong diploma 2 order: {v[0]} != {name}")
        metal, mix, mixyear = v[11:14]
        if metal is None:
            for next_line in lines[lineno + 1:lineno + 4]:
                nums = re.findall(r"\d+[,\.]\d+", next_line)
                if len(nums) >= 3:
                    metal, mix, mixyear = nums[-3:]
                    break
        if metal is None:
            raise ValueError(f"Cannot extract annual metal for {name}")
        d = lambda x: float(x.replace(",", "."))
        rows.append({
            "n": len(rows) + 1, "name": name, "mass": d(v[1]),
            "length": int(v[2]), "width": int(v[3]), "height": int(v[4]),
            "qty": int(v[5]), "per": int(v[6]), "molds": int(v[7]),
            "flask": v[8].replace("х", "x"), "flask_height": v[9],
            "pour": d(v[10]), "metal_source": d(metal),
            "mix_one": d(mix), "mix_year": d(mixyear), "machine": "ИЛ-225",
        })
    if len(rows) != 20:
        raise ValueError(f"Diploma 2: expected 20 positions, got {len(rows)}")
    return rows


def col_name(i: int) -> str:
    s = ""
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def cell_xml(row: int, col: int, value, style: int = 0) -> str:
    addr = f"{col_name(col)}{row}"
    st = f' s="{style}"' if style else ""
    if value is None:
        return ""
    if isinstance(value, tuple) and value and value[0] == "formula":
        return (f'<c r="{addr}"{st}><f>{escape(value[1])}</f>'
                f'<v>{value[2]}</v></c>')
    if isinstance(value, (float, int)) and not isinstance(value, bool):
        return f'<c r="{addr}"{st}><v>{value}</v></c>'
    return (f'<c r="{addr}"{st} t="inlineStr"><is><t>'
            f'{escape(str(value))}</t></is></c>')


def sheet_xml(rows: list[list], widths: list[float], merge_title: bool = True) -> bytes:
    cols = "".join(
        f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>'
        for i, w in enumerate(widths, 1)
    )
    body = []
    for n, vals in enumerate(rows, 1):
        height = ' ht="35" customHeight="1"' if n in (1, 2) else (
            ' ht="56" customHeight="1"' if n in (3, 10) else "")
        style = 1 if n == 1 else 2 if n == 3 else 3 if n == 2 else 0
        cells = "".join(cell_xml(n, i, v, style) for i, v in enumerate(vals, 1))
        body.append(f'<row r="{n}"{height}>{cells}</row>')
    merges = (f'<mergeCells count="2"><mergeCell ref="A1:{col_name(len(widths))}1"/>'
              f'<mergeCell ref="A2:{col_name(len(widths))}2"/></mergeCells>'
              if merge_title else "")
    xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
           f'<dimension ref="A1:{col_name(len(widths))}{len(rows)}"/>'
           '<sheetViews><sheetView workbookViewId="0"><pane ySplit="3" topLeftCell="A4" '
           'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
           f'<cols>{cols}</cols><sheetData>{"".join(body)}</sheetData>'
           f'{merges}</worksheet>')
    return xml.encode("utf-8")


STYLES = b'''<?xml version="1.0" encoding="UTF-8"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="3"><font><sz val="11"/><name val="Calibri"/></font>
    <font><b/><color rgb="FFFFFFFF"/><sz val="15"/></font>
    <font><b/><color rgb="FFFFFFFF"/><sz val="11"/></font></fonts>
  <fills count="5"><fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF17324F"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF27577B"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFD9EAF4"/></patternFill></fill></fills>
  <borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="4"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFill="1"/>
    <xf numFmtId="0" fontId="2" fillId="3" borderId="0" xfId="0" applyFill="1"/>
    <xf numFmtId="0" fontId="0" fillId="4" borderId="0" xfId="0" applyFill="1"/></cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>'''


def write_xlsx(path: Path, sheets: list[tuple[str, bytes]]) -> None:
    root = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    wb_sheets = "".join(
        f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>'
        for i, (name, _) in enumerate(sheets, 1)
    )
    wb = ('<?xml version="1.0" encoding="UTF-8"?>'
          f'<workbook xmlns="{root}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
          f'<sheets>{wb_sheets}</sheets></workbook>')
    rel = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
           + "".join(
               f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"'
               f' Target="worksheets/sheet{i}.xml"/>'
               for i in range(1, len(sheets) + 1))
           + '<Relationship Id="rId99" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
           + '</Relationships>')
    types = ('<?xml version="1.0" encoding="UTF-8"?>'
             '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
             '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
             '<Default Extension="xml" ContentType="application/xml"/>'
             '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
             '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
             + "".join(
                 f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                 for i in range(1, len(sheets) + 1)) + '</Types>')
    rootrels = ('<?xml version="1.0" encoding="UTF-8"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                '</Relationships>')
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", types)
        z.writestr("_rels/.rels", rootrels)
        z.writestr("xl/workbook.xml", wb)
        z.writestr("xl/_rels/workbook.xml.rels", rel)
        z.writestr("xl/styles.xml", STYLES)
        for i, (_, sheet) in enumerate(sheets, 1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", sheet)


def build(typ: int, positions: list[dict]) -> Path:
    # Absolute figures from the printed totals row; deliberately NOT
    # overwritten by row sums or formulas.
    reported = (
        {"qty": 5271000, "forms": 1368325, "metal": 55986.0, "mix": 272157.2}
        if typ == 1 else
        {"qty": 9001281, "forms": 768151, "metal": 79814786.1, "mix": 99586.0}
    )
    titles = (
        ["№", "Отливка", "Масса с ЛПС, кг", "Габарит, мм", "Высота, мм",
         "Отливок/год", "Отливок в форме", "Форм/год (PDF)", "Опока L×W",
         "Высоты полуформ", "Заливка, кг/форму", "Металл/год, т",
         "Смесь/форму, м³", "Смесь/год, м³", "АФЛ"]
        if typ == 1 else
        ["Отливка", "Масса, кг", "Длина, мм", "Ширина, мм", "Высота, мм",
         "Отливок/год", "Отливок в форме", "Форм/год (PDF)", "Опока L×W",
         "Высоты полуформ", "Заливка, кг/форму", "Металл/год, кг",
         "Смесь/форму, м³", "Смесь/год, м³", "АФЛ"]
    )
    source_rows = [
        [f"Диплом {typ} — исходная ведомость, PDF стр. {27 if typ==1 else 25}"],
        ["Значения из PDF не исправлены; в «Сверка» показаны различия с формулами."],
        titles,
    ]
    import_rows = [
        [f"Диплом {typ} — контрольный ввод A:P"],
        ["ИСТОЧНИК — лист «Ведомость формовки»; H/M на этом листе вычисляемые."],
        ["№","Наименование","Масса с ЛПС, кг","Габарит, мм","Высота, мм",
         "Отливок/год с браком","Отливок/форму","Масса, т","Опока L, мм",
         "Опока W, мм","Опока верх/низ","Заливка кг/форма","Масса L×форм, т",
         "Смесь/форму, м³","Примечание","Машина"],
    ]
    for r in positions:
        src = (
            [r["n"], r["name"], r["mass"], r["dimensions"], r["height"],
             r["qty"], r["per"], r["molds"], r["flask"], r["flask_height"],
             r["pour"], r["metal_source"], r["mix_one"], r["mix_year"], r["machine"]]
            if typ == 1 else
            [r["name"], r["mass"], r["length"], r["width"], r["height"],
             r["qty"], r["per"], r["molds"], r["flask"], r["flask_height"],
             r["pour"], r["metal_source"], r["mix_one"], r["mix_year"], r["machine"]]
        )
        source_rows.append(src)
        lineno = 3 + r["n"]
        nr = math.ceil(r["qty"] / r["per"])
        l, w = r["flask"].split("x")
        dim = r.get("dimensions") or f"{r['length']}x{r['width']}"
        import_rows.append([
            r["n"], r["name"], r["mass"], dim, r["height"], r["qty"], r["per"],
            ("formula", f"F{lineno}*C{lineno}/1000", r["qty"]*r["mass"]/1000),
            int(l), int(w), r["flask_height"], r["pour"],
            ("formula", f"ROUNDUP(F{lineno}/G{lineno},0)*L{lineno}/1000",
             nr*r["pour"]/1000),
            r["mix_one"],
            ("Формы по PDF отличаются" if r["molds"] != nr else ""),
            r["machine"],
        ])
    source_rows.append([
        "ИТОГО (PDF)", None,None,None,None,reported["qty"],None,
        reported["forms"],None,None,None,reported["metal"],None,reported["mix"],None
    ])
    check_rows = [
        [f"Диплом {typ}: сверка источника и производных величин"],
        ["Исходные спорные числа сохранены без правки в первом листе."],
        ["Показатель","Итого PDF","Сумма строк PDF","По формуле","Строки − PDF","Замечание"],
        ["Отливок",reported["qty"],sum(r["qty"] for r in positions),
         sum(r["qty"] for r in positions),
         sum(r["qty"] for r in positions)-reported["qty"],""],
        ["Форм",reported["forms"],sum(r["molds"] for r in positions),
         sum(math.ceil(r["qty"]/r["per"]) for r in positions),
         sum(r["molds"] for r in positions)-reported["forms"],
         "Программа использует ceil(F/G), не исходное округление"],
        ["Металл ("+("т" if typ==1 else "кг")+")",
         reported["metal"],sum(r["metal_source"] for r in positions),
         sum(math.ceil(r["qty"]/r["per"])*r["pour"] for r in positions) /
             (1000 if typ == 1 else 1),
         sum(r["metal_source"] for r in positions)-reported["metal"],
         "Не заменяйте годный выпуск металлозавалкой"],
        ["Смесь, м³",reported["mix"],sum(r["mix_year"] for r in positions),
         sum(math.ceil(r["qty"]/r["per"])*r["mix_one"] for r in positions),
         sum(r["mix_year"] for r in positions)-reported["mix"],""],
        [],
        ["Строка","Отливка","Форм PDF","Форм ceil(F/G)",
         "Отклонение форм PDF", "L×форм − C×выпуск, т"],
    ]
    for r in positions:
        calc = math.ceil(r["qty"]/r["per"])
        check_rows.append([
            r["n"],r["name"],r["molds"],calc,r["molds"]-calc,
            round(calc*r["pour"]/1000-r["qty"]*r["mass"]/1000,5),
        ])
    OUT.mkdir(parents=True,exist_ok=True)
    filename = OUT / f"Диплом_{typ}_ведомость_формовки.xlsx"
    widths = [14,27,22,21,16,23,18,18,18,19,22,23,19,20,24]
    write_xlsx(filename, [
        ("Ведомость формовки",sheet_xml(source_rows,widths)),
        ("Импорт A-P",sheet_xml(import_rows,widths+[27])),
        ("Сверка",sheet_xml(check_rows,[38,28,25,29,25,65])),
    ])
    print(filename, len(positions), "positions", sum(r["qty"] for r in positions),
          "pieces; source", sum(r["molds"] for r in positions), "molds")
    return filename


if __name__ == "__main__":
    build(1, extract_1())
    build(2, extract_2())
