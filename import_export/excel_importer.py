# -*- coding: utf-8 -*-
"""
excel_importer.py
=================
Модуль импорта номенклатуры отливок из Excel-файла (casting_production_v4.xlsx).

Структура файла (по ТЗ):
    Строки 1-3 — заголовки/пояснения (пропускаются)
    Строка 4+  — данные отливок

Колонки:
    A — № п/п
    B — Наименование отливки
    C — Масса с ЛПС, кг
    D — Габарит, мм (диаметр Ø или Д×Ш)
    E — Высота, мм
    F — Годовая программа (шт. с учётом брака)
    G — Количество отливок в форме
    H — [ВЫЧИСЛЯЕМОЕ] Масса заливаемого металла в год, т
    I — Опока: длина, мм
    J — Опока: ширина, мм
    K — Опока: высота, мм
    L — Заливочная масса, кг
    M — [ВЫЧИСЛЯЕМОЕ] Масса металла в год (по заливу), т
    N — Объём формовочной и стержневой смеси, м³
    O — [ВЫЧИСЛЯЕМОЕ]
    P — Тип формовочной машины
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import openpyxl
from openpyxl.utils import get_column_letter

# Локальные импорты
from core.casting_item import CastingItem

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Исключения
# ---------------------------------------------------------------------------
class ImportError_(Exception):
    """Базовое исключение для ошибок импорта."""
    pass


class FileNotExistsError(ImportError_):
    pass


class InvalidFormatError(ImportError_):
    pass


class EmptyDataError(ImportError_):
    pass


# ---------------------------------------------------------------------------
# Вспомогательные функции парсинга
# ---------------------------------------------------------------------------
def _parse_dimension(value) -> Tuple[float, Optional[float]]:
    """
    Парсит габарит из ячейки.
    Поддерживает форматы:
        - 'Ø180'      → (180.0, None)      — цилиндрическая отливка
        - '130x150'   → (130.0, 150.0)     — прямоугольная
        - '130х150'   → (130.0, 150.0)     — русская 'х'
        - '180'       → (180.0, None)
    Возвращает: (основной_размер, второй_размер)
    """
    if value is None:
        return (0.0, None)

    s = str(value).strip().replace(" ", "")
    if not s:
        return (0.0, None)

    # Ø180 / Ø 180 / ⌀180
    m = re.match(r"[Ø⌀∅]\s*([\d.,]+)", s)
    if m:
        return (float(m.group(1).replace(",", ".")), None)

    # 130x150 / 130х150 / 130*150
    m = re.match(r"([\d.,]+)[xх×*]([\d.,]+)", s)
    if m:
        return (
            float(m.group(1).replace(",", ".")),
            float(m.group(2).replace(",", ".")),
        )

    # Просто число
    try:
        return (float(s.replace(",", ".")), None)
    except ValueError:
        logger.warning(f"Не удалось распарсить габарит: '{s}'")
        return (0.0, None)


def _parse_flask(value) -> Tuple[float, float, float]:
    """
    Парсит размеры опоки из ячейки.
    Формат: '900x600x200' / '900x600x200/200' (последнее игнорируем — высота одна)
    Возвращает: (длина, ширина, высота)
    """
    if value is None:
        return (0.0, 0.0, 0.0)

    s = str(value).strip().replace(" ", "")
    # Убираем дробную часть высоты (200/200 → 200)
    s = re.sub(r"/\d+", "", s)

    parts = re.split(r"[xх×*]", s)
    if len(parts) >= 3:
        try:
            return (
                float(parts[0].replace(",", ".")),
                float(parts[1].replace(",", ".")),
                float(parts[2].replace(",", ".")),
            )
        except ValueError:
            pass

    logger.warning(f"Не удалось распарсить размеры опоки: '{s}'")
    return (0.0, 0.0, 0.0)


def _safe_float(value, default: float = 0.0) -> float:
    """Безопасное преобразование в float."""
    if value is None:
        return default
    try:
        s = str(value).strip().replace(",", ".")
        return float(s) if s else default
    except (ValueError, TypeError):
        return default


def _safe_int(value, default: int = 0) -> int:
    """Безопасное преобразование в int."""
    if value is None:
        return default
    try:
        s = str(value).strip()
        return int(float(s)) if s else default
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# Результат предпросмотра
# ---------------------------------------------------------------------------
@dataclass
class ImportPreview:
    """
    Структура для передачи данных в диалог предпросмотра.
    Содержит сырые строки до создания CastingItem — чтобы пользователь мог
    увидеть и отклонить некорректные данные.
    """
    file_path: Path
    headers: List[str]
    rows: List[List]                # сырые данные для таблицы предпросмотра
    castings: List[CastingItem]     # готовые объекты
    warnings: List[str]             # предупреждения (пустые ячейки, странные значения)

    @property
    def total_castings(self) -> int:
        return len(self.castings)

    @property
    def total_forms_per_year(self) -> int:
        return sum(c.molds_per_year for c in self.castings)

    @property
    def total_metal_tons(self) -> float:
        """Общая масса заливаемого металла в год, тонн."""
        return sum(c.annual_metal_t for c in self.castings)


# ---------------------------------------------------------------------------
# Основной класс импортера
# ---------------------------------------------------------------------------
class ExcelImporter:
    """
    Импортер номенклатуры отливок из Excel.

    Использование:
        importer = ExcelImporter()
        preview = importer.load_preview(Path("casting_production_v4.xlsx"))
        # ... показать preview в диалоге ...
        if user_confirmed:
            importer.apply_to_project(preview, project)
    """

    # Индексы колонок (0-based для openpyxl после чтения в list)
    COL_NUM       = 0   # A — №
    COL_NAME      = 1   # B — Наименование
    COL_MASS_LPS  = 2   # C — Масса с ЛПС, кг
    COL_DIM       = 3   # D — Габарит
    COL_HEIGHT    = 4   # E — Высота
    COL_PROG      = 5   # F — Годовая программа
    COL_IN_FORM   = 6   # G — Кол-во в форме
    # COL_H       = 7   # H — [ВЫЧИСЛЯЕМОЕ]
    COL_FLASK_L   = 8   # I — Опока: длина
    COL_FLASK_W   = 9   # J — Опока: ширина
    COL_FLASK_H   = 10  # K — Опока: высота
    COL_POUR_MASS = 11  # L — Заливочная масса, кг
    # COL_M       = 12  # M — [ВЫЧИСЛЯЕМОЕ]
    COL_MIX_VOL   = 13  # N — Объём смеси, м³
    # COL_O       = 14  # O — [ВЫЧИСЛЯЕМОЕ]
    COL_MACHINE   = 15  # P — Тип машины

    MIN_COLS = 16  # до колонки P включительно

    DATA_START_ROW = 4  # данные начинаются со строки 4 (1-based в Excel)

    HEADERS = [
        "№", "Наименование", "Масса с ЛПС, кг", "Габарит, мм",
        "Высота, мм", "Год. программа, шт", "В форме, шт",
        "Металл/год, т",
        "Опока L, мм", "Опока W, мм", "Опока H, мм",
        "Залив. масса, кг", "Металл (зал.) т/год",
        "Объём смеси, м³", "—", "Тип машины",
    ]

    def __init__(self, file_path: Optional[Path] = None):
        self._warnings: List[str] = []
        self.file_path = Path(file_path) if file_path else None

    def parse(self, file_path: Optional[Path] = None) -> List[CastingItem]:
        """Direct GUI API; do not change the project on an import error."""
        source = Path(file_path) if file_path else self.file_path
        if source is None:
            raise ValueError("Укажите путь к Excel-файлу")
        return self.load_preview(source).castings

    # ------------------------------------------------------------------
    # Публичные методы
    # ------------------------------------------------------------------
    @staticmethod
    def _diploma_format(headers: tuple) -> str | None:
        """Recognize the two original 15-column diploma molding ledgers."""
        a = str(headers[0] or "").lower().strip() if headers else ""
        b = str(headers[1] or "").lower().strip() if len(headers) > 1 else ""
        # Diploma 1: № | Отливка | масса | размер | высота | ...
        # The ordinary A:P template also starts with №/Наименование:
        # a diploma additionally has a source field "Форм/год (PDF)"
        # in H and exactly 15 original physical columns.
        annual_forms_header = str(headers[7] or "").lower() if len(headers) > 7 else ""
        if (a == "№" and "отлив" in b and
                ("форм/год" in annual_forms_header or "pdf" in annual_forms_header)):
            return "diploma1"
        # Diploma 2: Отливка | Масса | длина | ширина | высота | ...
        if "отлив" in a and "масс" in b:
            return "diploma2"
        return None

    def _convert_diploma_row(
        self, row: tuple, row_num: int, kind: str,
    ) -> tuple:
        """Convert legacy diploma A:O ledger to importer A:P.

        Preserve the original annual forms/metals in the source sheet.
        Explicitly warn when source data disagree with the required
        ceil(F/G) and per-mold poured mass. No silently revised source.
        """
        if len(row) < 15:
            raise ValueError("Для ведомости диплома нужны колонки A:O")
        if kind == "diploma1":
            num, name, mass, dim, height, qty, per, source_forms, flask,                 halfheights, pour, source_metal, mix_one, source_mix, machine = row[:15]
            metal_unit = "т"
        else:
            name, mass, length, width, height, qty, per, source_forms, flask,                 halfheights, pour, source_metal, mix_one, source_mix, machine = row[:15]
            num = row_num - self.DATA_START_ROW + 1
            dim = f"{length}x{width}"
            metal_unit = "кг"
        n = _safe_int(qty)
        g = _safe_int(per)
        expected_forms = (n + g - 1) // g if n > 0 and g > 0 else 0
        actual_forms = _safe_int(source_forms)
        if expected_forms and actual_forms != expected_forms:
            self._warnings.append(
                f"Строка {row_num} ({name}): в дипломе {actual_forms} форм, "
                f"ceil({n}/{g}) = {expected_forms}. Для планирования "
                "используется округление вверх; исходное число остаётся в Excel.")
        casting_metal_t = (expected_forms * _safe_float(pour) / 1000
                           if expected_forms else 0)
        original_metal_t = (_safe_float(source_metal)
                            if metal_unit == "т" else _safe_float(source_metal) / 1000)
        if original_metal_t and abs(casting_metal_t - original_metal_t) > max(
                0.1, original_metal_t * 0.00001):
            self._warnings.append(
                f"Строка {row_num} ({name}): металл по исходному диплому "
                f"{original_metal_t:.3f} т, по L×ceil(F/G) "
                f"{casting_metal_t:.3f} т. Проверьте данные и округление.")
        dims = re.findall(r"\d+(?:[.,]\d+)?", str(flask or ""))
        if len(dims) < 2:
            self._warnings.append(
                f"Строка {row_num} ({name}): не распознана опока {flask!r}")
            dims = [None, None]
        return (
            num, name, mass, dim, height, qty, per, None,
            dims[0], dims[1], halfheights, pour, None, mix_one, None, machine,
        )

    @staticmethod
    def _is_teacher_molding_sheet(ws) -> bool:
        """Identify official course workbook's Table 8 by CONTENT, not filename.

        Таблица 1 and Таблица 2 have different engineering units. Never
        attempt to import them as A:P castings.
        """
        a = str(ws.cell(1, 1).value or "").strip().lower()
        b = str(ws.cell(1, 2).value or "").strip().lower()
        g = str(ws.cell(1, 7).value or "").strip().lower()
        h = str(ws.cell(1, 8).value or "").strip().lower()
        return (a.startswith("номер") and "наименован" in b
                and "с учетом брака" in g and "в форме" in h)

    def _convert_teacher_row(self, row: tuple, row_num: int,
                             machine: str) -> tuple[tuple, str]:
        """Official teacher sheet Table 8, A:P, data begin at row 7.

        Source A-P:
          A no, B name, C casting mass, D/E/F size, G pcs/year,
          H pcs/mold, I fractional source molds, J flask width/length,
          K two half-heights, L metal per mold, M source metal/year kg,
          N/O mixture, P machine (often merged down from first row).
        """
        if len(row) < 16:
            row = tuple(row) + (None,) * (16 - len(row))
        (num, name, mass, length, width, height, annual_pieces,
         per_mold, source_molds, flask, halfheights, pour_mass,
         source_metal, mix_one, source_mix, equipment) = row[:16]
        if not isinstance(num, (int, float)) or isinstance(num, bool):
            raise ValueError("Таблица 8: ожидается числовой № отливки")
        if not str(name or "").strip():
            raise ValueError("Таблица 8: отсутствует наименование")
        dims = re.findall(r"\d+(?:[.,]\d+)?", str(flask or ""))
        if len(dims) != 2:
            raise ValueError(f"Таблица 8: некорректные размеры опоки: {flask!r}")
        qty = _safe_int(annual_pieces)
        each = _safe_int(per_mold)
        if qty <= 0 or each <= 0:
            raise ValueError("Таблица 8: неверная программа G или количество H")
        forms = (qty + each - 1) // each
        source_forms = _safe_float(source_molds)
        if source_forms and abs(forms - source_forms) > 1e-6:
            self._warnings.append(
                f"Строка {row_num} ({name}): в таблице 8 {source_forms:g} "
                f"форм, для физической программы ceil({qty}/{each}) = {forms}.")
        reported_metal = _safe_float(source_metal)
        calculated_metal = forms * _safe_float(pour_mass)
        if reported_metal and abs(reported_metal - calculated_metal) > max(
                0.1, reported_metal * 1e-6):
            self._warnings.append(
                f"Строка {row_num} ({name}): металл в исходной таблице "
                f"{reported_metal:g} кг, при целом количестве форм "
                f"{calculated_metal:g} кг. Исходное значение не исправлено.")
        if equipment:
            machine = str(equipment)
        converted = (
            int(num), str(name).strip(), mass,
            f"{length}x{width}", height, qty, each, None,
            dims[0], dims[1], halfheights, pour_mass, None,
            mix_one, None, machine,
        )
        return converted, machine

    def _check_teacher_cross_tables(
        self, forms_rows: list[tuple],
        first_rows: list[tuple],
        second_rows: list[tuple],
    ) -> None:
        """Cross-check Table 8 against original Table 1 and Table 2.

        A missing supporting source or a discrepancy is a WARNING.
        The table of castings remains entirely based on Table 8: never
        silently overwrite teacher's source quantities or masses.
        """
        def rows_by_index(rows: list[tuple]) -> dict[int, tuple]:
            output = {}
            for row in rows:
                if (len(row) > 1 and isinstance(row[1], int)
                        and not isinstance(row[1], bool) and row[1] > 0):
                    output[row[1]] = row
            return output

        t1 = rows_by_index(first_rows)
        t2 = rows_by_index(second_rows)
        if not t1 and not t2:
            return
        for row in forms_rows:
            if not row or not isinstance(row[0], int):
                continue
            index = row[0]
            name = str(row[1] or "").strip()
            mass = _safe_float(row[2])
            pieces = _safe_float(row[6])
            if t1:
                source1 = t1.get(index)
                if source1 is None:
                    self._warnings.append(
                        f"Позиция {index} ({name}): отсутствует в Таблице 1")
                else:
                    name1 = str(source1[0] or "").strip()
                    mass1 = _safe_float(source1[8] if len(source1) > 8 else None)
                    if name1 != name or abs(mass1 - mass) > 1e-3:
                        self._warnings.append(
                            f"Позиция {index} ({name}): в Таблице 1 имя или "
                            f"масса с ЛПС ({mass1:g} кг) отличается от Таблицы 8")
            if t2:
                source2 = t2.get(index)
                if source2 is None:
                    self._warnings.append(
                        f"Позиция {index} ({name}): отсутствует в Таблице 2")
                else:
                    name2 = str(source2[0] or "").strip()
                    pieces2 = _safe_float(
                        source2[14] if len(source2) > 14 else None)
                    # Floating-point quantities in Table 2 become physical
                    # whole castings in Table 8; <0.5 discrepancy is rounding.
                    if name2 != name or abs(pieces2 - pieces) > 0.500001:
                        self._warnings.append(
                            f"Позиция {index} ({name}): программа с браком "
                            f"в Таблице 2 ({pieces2:g} шт.) не согласуется "
                            f"с Таблицей 8 ({pieces:g} шт.).")

    def load_preview(self, file_path: Path) -> ImportPreview:
        """
        Загружает файл и формирует предпросмотр.
        НЕ модифицирует project — только читает файл.
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotExistsError(f"Файл не найден: {file_path}")

        if file_path.suffix.lower() not in (".xlsx", ".xlsm"):
            raise InvalidFormatError(
                f"Неподдерживаемый формат: {file_path.suffix}. "
                "Требуется .xlsx или .xlsm"
            )

        self._warnings = []
        wb = openpyxl.load_workbook(file_path, data_only=True, read_only=True)
        try:
            teacher_sheet = next(
                (sheet for sheet in wb.worksheets
                 if self._is_teacher_molding_sheet(sheet)), None)
            ws = teacher_sheet or wb.active
            header = next(ws.iter_rows(
                min_row=3, max_row=3, values_only=True), ())
            diploma_kind = (None if teacher_sheet
                            else self._diploma_format(tuple(header)))
            first_row = 7 if teacher_sheet is not None else self.DATA_START_ROW
            rows_data = list(ws.iter_rows(
                min_row=first_row, values_only=True,
            ))
            if teacher_sheet is not None:
                table_1 = next(
                    (sheet for sheet in wb.worksheets
                     if sheet.title.strip().lower() == "таблица 1"), None)
                table_2 = next(
                    (sheet for sheet in wb.worksheets
                     if sheet.title.strip().lower() == "таблица 2"), None)
                table_1_rows = (list(table_1.iter_rows(
                    min_row=6, values_only=True)) if table_1 else [])
                table_2_rows = (list(table_2.iter_rows(
                    min_row=8, values_only=True)) if table_2 else [])
            else:
                table_1_rows = []
                table_2_rows = []
        finally:
            wb.close()
        if teacher_sheet is not None:
            self._check_teacher_cross_tables(
                rows_data, table_1_rows, table_2_rows)
            self._warnings.append(
                "Обнаружена ведомость преподавателя «Таблица 8». "
                "Импортируются только позиции из неё; «Таблицы 1–2» "
                "служат для сверки программы и брака. "
                "Дробное число форм округляется вверх по каждой позиции.")

        if not rows_data:
            raise EmptyDataError(
                f"В файле нет данных. Ожидалось начало со строки "
                f"{self.DATA_START_ROW}"
            )

        castings: List[CastingItem] = []
        preview_rows: List[List] = []

        last_teacher_machine = ""
        for row_num, row in enumerate(rows_data, start=first_row):
            # Пропускаем полностью пустые строки
            if all(cell is None or str(cell).strip() == "" for cell in row):
                continue

            if teacher_sheet is not None:
                # Final subtotal row has «Итого» in B and no number in A.
                if (not isinstance(row[0], (int, float))
                        or isinstance(row[0], bool)):
                    continue
                try:
                    row, last_teacher_machine = self._convert_teacher_row(
                        tuple(row), row_num, last_teacher_machine)
                except (TypeError, ValueError, IndexError) as exc:
                    self._warnings.append(
                        f"Строка {row_num}: пропущена, {exc}")
                    continue
            # Source diploma has its own A:O layout. The importer converts
            # to A:P automatically by sheet headers, not by filename.
            if diploma_kind:
                # Source totals / notes on lower rows are not castings.
                if (_safe_float(row[2]) <= 0 if diploma_kind == "diploma1"
                    else _safe_float(row[1]) <= 0):
                    continue
                try:
                    row = self._convert_diploma_row(
                        tuple(row), row_num, diploma_kind)
                except (ValueError, IndexError, TypeError) as exc:
                    self._warnings.append(
                        f"Строка {row_num}: не распознана ведомость ({exc})")
                    continue
            # Проверка минимального количества колонок
            if len(row) < self.MIN_COLS:
                self._warnings.append(
                    f"Строка {row_num}: недостаточно колонок "
                    f"({len(row)} < {self.MIN_COLS}). Пропущена."
                )
                continue

            casting, preview_row = self._parse_row(row, row_num)
            if casting is not None:
                castings.append(casting)
                preview_rows.append(preview_row)

        if not castings:
            raise EmptyDataError(
                "Не удалось прочитать ни одной корректной записи. "
                "Проверьте структуру файла."
            )

        return ImportPreview(
            file_path=file_path,
            headers=self.HEADERS,
            rows=preview_rows,
            castings=castings,
            warnings=self._warnings.copy(),
        )

    def apply_to_project(self, preview: ImportPreview, project) -> None:
        """
        Заменяет номенклатуру в project на импортированную.
        Эмитит сигнал params_changed.
        """
        project.castings = preview.castings
        project.source_file = str(preview.file_path)

        # Пересчитываем суммарные поля проекта
        if hasattr(project, "recalc_totals"):
            project.recalc_totals()

        # Сигналим GUI о необходимости обновления всех вкладок
        if hasattr(project, "params_changed"):
            project.params_changed.emit()

        logger.info(
            f"Импортировано {preview.total_castings} позиций, "
            f"{preview.total_forms_per_year} форм/год, "
            f"{preview.total_metal_tons:.1f} т металла/год"
        )

    # ------------------------------------------------------------------
    # Внутренние методы
    # ------------------------------------------------------------------
    def _parse_row(
        self, row: tuple, row_num: int
    ) -> Tuple[Optional[CastingItem], Optional[List]]:
        """
        Парсит одну строку Excel.
        Возвращает: (CastingItem | None, preview_row | None)
        """
        # --- Обязательные поля ---
        num = _safe_int(row[self.COL_NUM])
        name = str(row[self.COL_NAME] or "").strip()

        if not name:
            self._warnings.append(
                f"Строка {row_num}: пустое наименование. Пропущена."
            )
            return (None, None)

        mass_lps = _safe_float(row[self.COL_MASS_LPS])
        height = _safe_float(row[self.COL_HEIGHT])
        forms_per_year = _safe_int(row[self.COL_PROG])
        in_form = _safe_int(row[self.COL_IN_FORM])
        pour_mass = _safe_float(row[self.COL_POUR_MASS])
        mix_volume = _safe_float(row[self.COL_MIX_VOL])
        machine = str(row[self.COL_MACHINE] or "").strip()

        # --- Габарит ---
        dim1, dim2 = _parse_dimension(row[self.COL_DIM])
        if dim1 == 0.0:
            self._warnings.append(
                f"Строка {row_num} ({name}): не распознан габарит "
                f"'{row[self.COL_DIM]}'"
            )

        # --- Опока ---
        flask_l, flask_w, flask_h = _parse_flask(
            f"{row[self.COL_FLASK_L]}x{row[self.COL_FLASK_W]}x{row[self.COL_FLASK_H]}"
        )
        if flask_l == 0 or flask_w == 0:
            self._warnings.append(
                f"Строка {row_num} ({name}): не распознаны размеры опоки"
            )

        # Столбец F — количество ОТЛИВОК в год с учётом брака.
        # Столбец G — сколько отливок размещено в одной форме.
        # Число форм = ceil(F/G). Это не F и не F*G!
        if mass_lps <= 0 or forms_per_year <= 0 or in_form <= 0:
            self._warnings.append(
                f"Строка {row_num} ({name}): нужны положительные C, F и G")
            return None, None
        if flask_l <= 0 or flask_w <= 0 or flask_h <= 0:
            self._warnings.append(
                f"Строка {row_num} ({name}): нужны размеры опоки I, J, K")
            return None, None
        molds = (forms_per_year + in_form - 1) // in_form
        # L — масса металла, заливаемого в ОДНУ форму, включая все
        # отливки, литниковую систему и прибыли.
        effective_pour_mass = pour_mass
        pouring_mass_estimated = effective_pour_mass <= 0
        if pouring_mass_estimated:
            effective_pour_mass = mass_lps * in_form
            self._warnings.append(
                f"Строка {row_num} ({name}): L не заполнено; "
                "заливочная масса оценена как C×G. Проверьте ЛПС.")
        # C — масса одной отливки С ЛПС. Чистая масса без ЛПС неизвестна,
        # не выдаём её за рассчитанный показатель.
        if effective_pour_mass + 1e-9 < mass_lps * in_form:
            self._warnings.append(
                f"Строка {row_num} ({name}): L={effective_pour_mass:g} кг/форму "
                f"меньше C×G={mass_lps * in_form:g} кг. "
                "Проверьте трактовку массы с ЛПС и массу заливки; "
                "значения не исправлены автоматически.")
        metal_year_tons = effective_pour_mass * molds / 1000.0
        # K допускает одну высоту или две полуформы вида 200/250.
        raw_h = str(row[self.COL_FLASK_H] or "").replace(",", ".")
        height_parts = re.findall(r"\d+(?:\.\d+)?", raw_h)
        if len(height_parts) >= 2:
            upper, lower = float(height_parts[0]), float(height_parts[1])
        else:
            upper = lower = flask_h
            self._warnings.append(
                f"Строка {row_num} ({name}): в K указана одна высота; "
                "приняты одинаковые высоты верхней и нижней полуформ.")
        def _dim(n: float) -> str:
            return str(int(n)) if float(n).is_integer() else str(n)
        casting = CastingItem(
            index=num or row_num - self.DATA_START_ROW + 1,
            name=name,
            mass_with_LPS_kg=mass_lps,
            mass_casting_kg=0.0,
            dimensions_mm=str(row[self.COL_DIM] or ""),
            height_mm=height,
            length_mm=dim1,
            width_mm=dim2 or 0.0,
            annual_qty_pcs=forms_per_year,  # F уже учитывает брак
            annual_qty_with_brak=forms_per_year,
            brak_pct=0.0,                 # исключить двойное начисление брака
            molds_per_year=molds,
            castings_per_mold=in_form,
            pouring_mass_estimated=pouring_mass_estimated,
            flask_size_mm=f"{_dim(flask_l)}x{_dim(flask_w)}x{_dim(upper)}/{_dim(lower)}",
            pouring_mass_kg=effective_pour_mass,
            annual_metal_t=metal_year_tons,
            mix_volume_m3=mix_volume,
            molding_machine=machine,
        )
        # Строка для предпросмотра
        preview_row = [
            num, name, f"{mass_lps:.2f}",
            f"Ø{dim1:.0f}" if dim2 is None else f"{dim1:.0f}×{dim2:.0f}",
            f"{height:.0f}", forms_per_year, in_form,
            f"{metal_year_tons:.2f}",
            f"{flask_l:.0f}", f"{flask_w:.0f}", f"{upper:.0f}/{lower:.0f}",
            f"{effective_pour_mass:.2f}", f"{metal_year_tons:.2f}",
            f"{mix_volume:.3f}", "—", machine,
        ]

        return (casting, preview_row)