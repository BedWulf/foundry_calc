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
        ws = wb.active

        try:
            header = next(ws.iter_rows(
                min_row=3, max_row=3, values_only=True), ())
            diploma_kind = self._diploma_format(tuple(header))
            rows_data = list(ws.iter_rows(
                min_row=self.DATA_START_ROW,
                values_only=True,
            ))
        finally:
            wb.close()

        if not rows_data:
            raise EmptyDataError(
                f"В файле нет данных. Ожидалось начало со строки "
                f"{self.DATA_START_ROW}"
            )

        castings: List[CastingItem] = []
        preview_rows: List[List] = []

        for row_num, row in enumerate(rows_data, start=self.DATA_START_ROW):
            # Пропускаем полностью пустые строки
            if all(cell is None or str(cell).strip() == "" for cell in row):
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
        in_form = _safe_int(row[self.COL_IN_FORM]) or 1
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
        if effective_pour_mass <= 0:
            effective_pour_mass = mass_lps * in_form
            self._warnings.append(
                f"Строка {row_num} ({name}): L не заполнено; "
                "заливочная масса оценена как C×G. Проверьте ЛПС.")
        # C — масса одной отливки С ЛПС. Чистая масса без ЛПС неизвестна,
        # не выдаём её за рассчитанный показатель.
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