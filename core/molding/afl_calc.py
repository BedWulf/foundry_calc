"""Расчёт количества автоматических формовочных линий (АФЛ).

Эталонные формулы («Sample Diploma.pdf», лист 25; «Sample Diploma 2.pdf»,
лист 23):

    Nф.год = Г · k_бр.доп / m_отл                     — годовое число форм, шт
    Pр     = Nф.год / (Фд · k_мн)                     — потребная произв., ф/ч
    П₁     = Pр / q_ном                               — расчётное число линий
    Кзо    = Pр / (Ппр · q_ном)                       — коэффициент загрузки

где Г — годовой выпуск годного литья группы, т; m_отл — масса отливки
с ЛПС, кг; Фд — действительный фонд времени оборудования, ч; k_мн —
коэффициент многостаночности/число форм в одном цикле (для АФЛ ИЛ-225
в дипломе принят 1); q_ном — паспортная производительность линии, ф/ч.

Особенность подбора АФЛ (в отличие от печей): одна линия обслуживает
НЕСКОЛЬКО групп номенклатуры, поэтому расчётное число линий П₁ всегда
округляется ВВЕРХ до целого (``ceil``), а не «до загрузки ≤ 0.85» — это
соответствует диплому, где линии дополнительно догружаются номенклатурой.
Коэффициент загрузки Кзо может оказаться ниже оптимальных 0.70–0.85;
в UI он подсвечивается как недогрузка.

Пример по данным диплома: группа 4 000 т/год, отливка 4 кг →
Nф = 1 000 000 форм; Pр = 1 000 000/3 890 = 257 ф/ч; ИЛ-225 (240 ф/ч) →
П₁ = 1.07 → принято 2 линии, Кзо = 0.536 (недогрузка — компенсируется
загрузкой других групп на ту же линию).
"""
import hashlib
import json
import math
from datetime import datetime
from typing import Any, Dict, List, Optional

from config import DATA_DIR
from data.loader import DataLoader

#: Справочник формовочного оборудования (Шаг 1) — только через DATA_DIR.
MOLDING_LINES_FILE = "equipment/molding_lines.json"
#: Пользовательские линии, добавленные через UI-диалог (требование №5).
CUSTOM_MOLDING_FILE = "user_data/custom_molding_lines.json"


def calc_annual_molds(annual_output_t: float, unit_mass_kg: float,
                      brak_pct: float = 0.0) -> int:
    """Годовое количество форм для группы одинаковых отливок.

    Args:
        annual_output_t: годовой выпуск годного литья группы, т
        unit_mass_kg: масса одной отливки с ЛПС, кг
        brak_pct: дополнительный процент выпуска на брак (по позиции)

    Returns:
        Годовое число форм, шт (округление вверх); 0 при некорректных данных
    """
    if annual_output_t <= 0 or unit_mass_kg <= 0:
        return 0
    need_t = annual_output_t * (1.0 + brak_pct / 100.0)
    return int(math.ceil(need_t * 1000.0 / unit_mass_kg))


def calc_required_productivity(annual_molds: int, fund_hours: float) -> float:
    """Потребная производительность формовки, форм/час (формула диплома).

    Args:
        annual_molds: годовое количество форм, шт
        fund_hours: действительный годовой фонд времени оборудования, ч

    Returns:
        Потребная производительность, ф/ч
    """
    if fund_hours <= 0:
        return 0.0
    return annual_molds / fund_hours


def calc_lines_count(required_productivity: float, nominal_productivity_h: float,
                     max_load_factor: float = 1.0) -> Dict[str, Any]:
    """Рассчитать число линий и коэффициент загрузки.

    Число линий принимается ближайшим целым, при котором Кзо не превышает
    ``max_load_factor``. По умолчанию 1.0 — «всегда ceil», что соответствует
    диплому: линия не может работать с загрузкой выше 100 %, а возникшую
    недогрузку компенсируют загрузкой на неё других групп номенклатуры.

    Args:
        required_productivity: потребная производительность, ф/ч
        nominal_productivity_h: паспортная производительность линии, ф/ч
        max_load_factor: верх допустимой загрузки (0.70–0.85 для печей,
            1.0 — для формовочных линий)

    Returns:
        Словарь: ``p1_required`` (расчётное число линий), ``count``
        (принятое, не менее 1 при ненулевой программе), ``load_factor``
    """
    if nominal_productivity_h <= 0:
        return {"p1_required": 0.0, "count": 0, "load_factor": 0.0}
    p1 = required_productivity / nominal_productivity_h
    count = max(1, math.ceil(p1 / max_load_factor)) if p1 > 0 else 0
    load = p1 / count if count else 0.0
    return {"p1_required": round(p1, 3), "count": count,
            "load_factor": round(load, 3)}


class MoldingCalculator:
    """Подбор формовочных линий под программу цеха с фильтрацией по материалу."""

    def __init__(self, loader: Optional[DataLoader] = None):
        """Инициализировать калькулятор.

        Args:
            loader: загрузчик справочников (по умолчанию — config.DATA_DIR)
        """
        self.loader = loader or DataLoader(DATA_DIR)

    # ---------- справочник + пользовательские линии ----------
    def _all_lines(self) -> List[Dict[str, Any]]:
        """Объединённый список линий: справочник + пользовательские."""
        lines = list(self.loader.load_list(MOLDING_LINES_FILE, key="lines"))
        lines.extend(self.load_custom_lines())
        return lines

    @staticmethod
    def custom_path() -> Any:
        """Путь к файлу пользовательских формовочных линий."""
        return DATA_DIR.parent / "user_data" / "custom_molding_lines.json"

    def load_custom_lines(self) -> List[Dict[str, Any]]:
        """Загрузить пользовательские линии (файл может отсутствовать)."""
        path = self.custom_path()
        if not path.exists():
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            return []
        lines = data.get("lines", []) if isinstance(data, dict) else data
        return [l for l in lines if isinstance(l, dict)]

    def add_custom_line(self, line: Dict[str, Any]) -> Dict[str, Any]:
        """Добавить пользовательскую формовочную линию и сохранить в JSON.

        Args:
            line: карточка линии (name/type/specs.nominal_productivity_molds_h/
                applicable_for.materials); id проставляется автоматически

        Returns:
            Сохранённая карточка с полями ``id`` и ``custom=True``
        """
        record: Dict[str, Any] = {**line, "custom": True}
        if not record.get("id"):
            raw = f"{record.get('name', 'line')}|{datetime.now().isoformat()}"
            record["id"] = "custom_" + hashlib.md5(raw.encode("utf-8")).hexdigest()[:8]
        records = [r for r in self.load_custom_lines()
                   if r.get("id") != record["id"]]
        records.append(record)
        path = self.custom_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"version": "1.0", "lines": records}, f,
                      indent=2, ensure_ascii=False)
        return record

    # ---------- подбор ----------
    def find_lines(
        self,
        material_category: str,
        annual_molds: int,
        working_hours: float = 3890.0,
        max_casting_mass_kg: float = 0.0,
        k_multi: float = 1.0,
        top_n: int = 5,
    ) -> List[Dict[str, Any]]:
        """Подобрать подходящие формовочные линии.

        Args:
            material_category: категория сплава ('steel'/'cast_iron'/'aluminum')
            annual_molds: годовое количество форм, шт
            working_hours: действительный фонд времени оборудования, ч
            max_casting_mass_kg: наибольшая заливочная масса формы в группе, кг
                (фильтр по металлоемкости; 0 — без фильтра)
            k_multi: коэффициент многостаночности (число форм в цикле), по молч. 1
            top_n: сколько лучших вариантов вернуть

        Returns:
            Список карточек линий с расчётными ключами ``_score``,
            ``_num_required``, ``_load_factor``, ``_molds_required``
        """
        required_productivity = calc_required_productivity(annual_molds, working_hours) \
            / k_multi if k_multi else calc_required_productivity(annual_molds, working_hours)

        candidates: List[Dict[str, Any]] = []
        for line in self._all_lines():
            app = line.get("applicable_for", {})
            if material_category not in app.get("materials", []):
                continue
            mass_range = app.get("casting_mass_range_kg") or [0, 0]
            if max_casting_mass_kg > 0 and max_casting_mass_kg > float(mass_range[1]):
                continue

            nominal = float(line.get("specs", {}).get(
                "nominal_productivity_molds_h", 0) or 0)
            if nominal <= 0:
                continue

            res = calc_lines_count(required_productivity, nominal)
            score = self._score_line(line, res["load_factor"], res["count"])
            # card_fields — переопределение строки характеристик карточки в
            # EquipmentPicker (единицы ф/ч и опки, а не т/т·ч); формат:
            # [(ключ в specs, человекочитаемая подпись), ...]
            candidates.append({
                **line,
                "_score": score,
                "_num_required": res["count"],
                "_load_factor": res["load_factor"],
                "_p1_required": res["p1_required"],
                "_molds_required": round(required_productivity, 2),
                "card_fields": [
                    ("flask_size_mm", "Опки"),
                    ("nominal_productivity_molds_h", "Производительность, ф/ч"),
                    ("max_mold_metal_kg", "Макс. металл в форме"),
                    ("installed_power_kw", "Мощность, кВт"),
                ],
            })

        candidates.sort(
            key=lambda x: (
                bool(x.get("applicable_for", {}).get("recommended", False)),
                x["_score"],
                -x["_num_required"],
            ),
            reverse=True,
        )
        return candidates[:top_n]

    @staticmethod
    def _score_line(line: Dict[str, Any], load_factor: float,
                    num_lines: int = 1) -> float:
        """Балл релевантности линии (0..1+): идеальная загрузка 0.70–0.85.

        Args:
            line: карточка линии
            load_factor: коэффициент загрузки при принятом числе линий
            num_lines: принятое число линий (штраф за раздробленность парка)

        Returns:
            Итоговый балл
        """
        lo, hi = 0.70, 0.85
        if lo <= load_factor <= hi:
            base = 1.0
            bonus = 0.15 * (load_factor - lo) / (hi - lo)
        else:
            dist = lo - load_factor if load_factor < lo else load_factor - hi
            base = 1.0 / (1.0 + 5 * dist ** 2)
            bonus = -0.3 * min((load_factor - hi) / hi, 0.5) if load_factor > hi else 0.0
        penalty = 1.0 / (1.0 + 0.05 * max(num_lines - 1, 0))
        return round((base + bonus) * penalty, 3)

    def get_line_by_id(self, line_id: str) -> Dict[str, Any]:
        """Найти линию в справочнике (или пользовательских) по id."""
        for line in self._all_lines():
            if line.get("id") == line_id:
                return line
        return {}
