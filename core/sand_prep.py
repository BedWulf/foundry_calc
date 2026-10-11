"""Расчёт смесеприготовительного отделения (раздел 6 дипломов).

Логика полностью повторяет эталонные формулы обоих дипломов:

    n  = Q · k_н / (q · Тд)          — потребное число установок;
    Рд = pick_unit_count(n)          — принятое число (Кзо ≤ 0.85, методика
                                      диплома 2: Рд = n / (0.7 ÷ 0.85));
    кз = n / Рд                      — фактический коэффициент загрузки,

где Q — годовой расход смеси (в м3/год для объёмного оборудования и в т/год
для дробилок), k_н = 1.05 — коэффициент неравномерности, q — паспортная
производительность, Тд — действительный годовой фонд времени оборудования.

Расход смеси из геометрии форм (методичка, раздел 6):

    V_год   = Nформ · Vопки                       — геометрический объём, м3/год
    объём формы минус металл и стержни            — уплотнённая смесь в форме
    Q_смеси = V_упл · ρупл / ρнеуплотн            — пересчёт в неуплотнённую
                                                  (её готовят бегуны)

Позиции отделения (как в дипломах):

    • molding_mix — приготовление формовочной смеси (бегуны 15126);
    • core_mix    — приготовление стержневой смеси (1А11 / С-110);
    • lumps       — раздавливание комьев регенерации (Д3Г/Д4Г, т/ч):
                    Q = доля комьев × расход формовочной смеси, т/год;
    • sieving     — просев (сита 175М/179, м3/ч): весь объём регенерации;
    • cooling     — охлаждение/стабилизация (11311, м3/ч);
    • magnetic_separation — сепаратор ШЭ100–80 (обязательная позиция).

Справочник: ``data/equipment/mixers.json`` (ключ ``mixers``), составы смесей
и плотности: ``data/materials/mix_compositions.json``. Пользовательское
оборудование: ``user_data/custom_mixers.json``. Только JSON, без SQLite.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import DATA_DIR
from data.loader import DataLoader

#: Справочник смесеприготовительного оборудования — всегда через DATA_DIR.
MIXERS_FILE: str = "equipment/mixers.json"

#: Составы смесей и плотности — тоже через DATA_DIR.
MIX_COMPOSITIONS_FILE: str = "materials/mix_compositions.json"

#: Идеальная зона загрузки парка (методичка, 0.70–0.85).
LOAD_OPTIMAL_MIN: float = 0.70
LOAD_OPTIMAL_MAX: float = 0.85

#: Коэффициент неравномерности нагрузки (оба диплома: КН = 1.05).
K_UNEVEN: float = 1.05

#: Запас на объём стержневой смеси в форме (диплом 2 пересчитывает стержневую
#: смесь по плотности ГТС с коэффициентом 1.55/1.1 ≈ 1.41).
CORE_MIX_FACTOR: float = 155.0 / 110.0

#: Плотности по методичке (раздел 6), т/м3.
DENSITY_LOOSE_MIX: float = 1.25      # неуплотнённая смесь с кварцевым песком
DENSITY_TAMPED_SHAKE: float = 1.65   # уплотнённая встряхиванием
DENSITY_TAMPED_PRESS: float = 1.8    # уплотнённая прессованием (АФЛ)
DENSITY_GTS: float = 1.55            # глинисто-синтетическая (стержневая)
DENSITY_STEEL: float = 7.8           # плотность стали, т/м3

#: Доля комьев в отработанной формовочной смеси при регенерации
#: (диплом 1: «Q – 10–15% расчетного расхода смеси», диплом 2: «Q – 10%»).
LUMPS_SHARE_DEFAULT: float = 0.10

#: Среднее число стержней на форму, если номенклатура не задана.
DEFAULT_CORES_PER_MOLD: float = 1.5

#: Средняя масса одного стержня, кг (ориентир методички).
AVG_CORE_MASS_KG: float = 3.0

#: Порядок позиций в UI (сначала приготовление смеси, затем регенерация —
#: как в разделах 6.2/6.3 дипломов).
OPERATION_ORDER: List[str] = [
    "molding_mix", "core_mix", "lumps", "sieving", "cooling",
    "magnetic_separation",
]

#: Человекочитаемые названия операций.
OPERATION_TITLES: Dict[str, str] = {
    "molding_mix": "Приготовление формовочной смеси",
    "core_mix": "Приготовление стержневой смеси",
    "lumps": "Раздавливание комьев (регенерация)",
    "sieving": "Просев смеси (регенерация)",
    "cooling": "Охлаждение и стабилизация смеси",
    "magnetic_separation": "Магнитная сепарация",
}

#: Единицы измерения производительности.
UNIT_LABELS: Dict[str, str] = {"m3_h": "м³/ч", "t_h": "т/ч"}


def pick_unit_count(n_required: float,
                    max_load_factor: float = LOAD_OPTIMAL_MAX) -> int:
    """Принять число установок по методике диплома 2.

    Диплом: ``Рд = n / (0.7 ÷ 0.85)`` — парк берут не ``ceil(n)``, а
    ближайшее целое, при котором загрузка не превышает верх оптимальной
    зоны. Пример диплома 2: n = 5.31 → Рд = 7, кз = 0.76.

    Args:
        n_required: расчётное число установок
        max_load_factor: верх допустимой загрузки (0.85)

    Returns:
        Принятое число установок (не меньше 1 при положительном запросе)
    """
    if n_required <= 0:
        return 0
    return max(math.ceil(n_required), math.ceil(n_required / max_load_factor))


def load_factor(n_required: float, units: int) -> float:
    """Коэффициент загрузки парка: ``кз = n / Рд``."""
    if units <= 0:
        return 0.0
    return round(n_required / units, 3)


def machine_productivity(machine: Dict[str, Any]) -> float:
    """Паспортная (номинальная) производительность установки, м3/ч или т/ч.

    Берёт ``specs.productivity_m3_h`` / ``specs.productivity_t_h``; для
    диапазонов («9–12») дополнительно доступно ``productivity_min_*``.

    Args:
        machine: карточка из справочника mixers.json

    Returns:
        Производительность; 0, если данных нет
    """
    specs = machine.get("specs", {})
    unit = machine.get("unit", "m3_h")
    key = "productivity_t_h" if unit == "t_h" else "productivity_m3_h"
    val = float(specs.get(key, 0) or 0)
    if val <= 0:  # пользовательская карточка могла прийти с generic-полем
        val = float(specs.get("productivity", 0) or 0)
    return val


def calc_sand_volumes(annual_molds: int,
                      mold_volume_m3: float,
                      metal_per_mold_kg: float,
                      cores_mass_per_mold_kg: float,
                      tamped_density: float = DENSITY_TAMPED_PRESS,
                      loose_density: float = DENSITY_LOOSE_MIX,
                      ) -> Dict[str, float]:
    """Годовые объёмы и массы смеси по геометрии форм.

    В форме занимает объём металл + стержни; остальное — формовочная смесь
    в уплотнённом состоянии. Бегуны же готовят НЕуплотнённую смесь, поэтому
    годовой объём для подбора оборудования: ``V_см = V_упл · ρупл / ρнеупл``.

    Args:
        annual_molds: годовое число форм, шт
        mold_volume_m3: объём одной опки в свету, м3
        metal_per_mold_kg: средняя масса металла в форме (с ЛПС), кг
        cores_mass_per_mold_kg: суммарная масса стержней в форме, кг
        tamped_density: плотность уплотнённой смеси, т/м3
        loose_density: плотность неуплотнённой смеси, т/м3

    Returns:
        Словарь: ``mold_volume_total_m3``, ``sand_volume_tamped_m3``,
        ``sand_volume_loose_m3``, ``sand_mass_tamped_t``,
        ``sand_mass_loose_t``
    """
    if annual_molds <= 0 or mold_volume_m3 <= 0:
        return {"mold_volume_total_m3": 0.0, "sand_volume_tamped_m3": 0.0,
                "sand_volume_loose_m3": 0.0, "sand_mass_tamped_t": 0.0,
                "sand_mass_loose_t": 0.0}
    total = annual_molds * mold_volume_m3
    occupied = (metal_per_mold_kg / 1000.0 / DENSITY_STEEL
                + cores_mass_per_mold_kg / 1000.0 / DENSITY_GTS)
    sand_tamped_per_mold = max(mold_volume_m3 - occupied, 0.0)
    sand_tamped = annual_molds * sand_tamped_per_mold
    sand_loose = sand_tamped * tamped_density / loose_density
    return {
        "mold_volume_total_m3": round(total, 1),
        "sand_volume_tamped_m3": round(sand_tamped, 1),
        "sand_volume_loose_m3": round(sand_loose, 1),
        "sand_mass_tamped_t": round(sand_tamped * tamped_density, 1),
        "sand_mass_loose_t": round(sand_loose * loose_density, 1),
    }


class SandPrepCalculator:
    """Подбор оборудования смесеприготовительного отделения."""

    def __init__(self, loader: Optional[DataLoader] = None):
        """Инициализировать калькулятор.

        Args:
            loader: загрузчик справочников (по умолчанию — config.DATA_DIR)
        """
        self.loader = loader or DataLoader(DATA_DIR)

    # ---------- справочник + пользовательские карточки ----------
    def _all_mixers(self) -> List[Dict[str, Any]]:
        """Объединённый список: справочник + пользовательское оборудование."""
        machines = list(self.loader.load_list(MIXERS_FILE, key="mixers"))
        machines.extend(self.load_custom_mixers())
        return machines

    @staticmethod
    def custom_path() -> Path:
        """Путь к файлу пользовательского смесеприготовительного оборудования."""
        return DATA_DIR.parent / "user_data" / "custom_mixers.json"

    def load_custom_mixers(self) -> List[Dict[str, Any]]:
        """Загрузить пользовательские установки (файл может отсутствовать)."""
        path = self.custom_path()
        if not path.exists():
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            return []
        machines = data.get("mixers", []) if isinstance(data, dict) else data
        return [m for m in machines if isinstance(m, dict)]

    def add_custom_mixer(self, machine: Dict[str, Any]) -> Dict[str, Any]:
        """Добавить пользовательскую установку и сохранить в JSON.

        Args:
            machine: карточка (name/type/operation/unit/specs.productivity +
                applicable_for.materials); id проставляется автоматически

        Returns:
            Сохранённая карточка с полями ``id`` и ``custom=True``
        """
        record: Dict[str, Any] = {**machine, "custom": True}
        if not record.get("id"):
            raw = f"{record.get('name', 'mixer')}|{datetime.now().isoformat()}"
            record["id"] = "custom_" + hashlib.md5(raw.encode("utf-8")).hexdigest()[:8]
        specs = dict(record.get("specs", {}))
        unit = record.get("unit", "m3_h")
        key = "productivity_t_h" if unit == "t_h" else "productivity_m3_h"
        if float(specs.get(key, 0) or 0) <= 0:
            specs[key] = float(specs.get("productivity", 0) or 0)
        record["specs"] = specs
        records = [r for r in self.load_custom_mixers()
                   if r.get("id") != record["id"]]
        records.append(record)
        path = self.custom_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"version": "1.0", "mixers": records}, f,
                      indent=2, ensure_ascii=False)
        return record

    # ---------- скоринг ----------
    @staticmethod
    def _score_machine(machine: Dict[str, Any], n_required: float,
                       units: int, lf: float) -> float:
        """Балл релевантности установки (чем выше, тем лучше).

        Приоритеты (согласно требованию «дипломы — примеры, показываем
        более оптимальные варианты первыми»):

        1. Загрузка парка в зоне 0.70–0.85 — базовый балл 1.0; вне зоны балл
           падает пропорционально удалению от границы.
        2. Штраф за раздробленность парка только при перегрузе позиции
           (n > 1): больше единиц — дороже содержание. При n < 1 установка
           нужна одна у всех моделей, поэтому число машин различать нельзя —
           там решает близость Кзо к зоне и «паспортная» рекомендация.
        3. Минорный бонус за ``recommended`` (tie-break).

        Args:
            machine: карточка установки
            n_required: расчётное потребное число установок
            units: принятое число установок
            lf: коэффициент загрузки парка

        Returns:
            Балл ~0..1.25
        """
        if units <= 0 or n_required <= 0:
            return -1.0
        if LOAD_OPTIMAL_MIN <= lf <= LOAD_OPTIMAL_MAX:
            base = 1.0
        elif lf < LOAD_OPTIMAL_MIN:
            base = max(0.0, 1.0 - (LOAD_OPTIMAL_MIN - lf) * 2.5)
        else:
            base = max(0.0, 1.0 - (lf - LOAD_OPTIMAL_MAX) * 4.0)
        score = base
        if n_required > 1.0:
            score -= 0.06 * max(units - 1, 0)
        if bool(machine.get("applicable_for", {}).get("recommended", False)):
            score += 0.03
        return round(score, 4)

    # ---------- подбор по одной позиции ----------
    def find_for_operation(
        self,
        operation: str,
        quantity: float,
        material_category: str,
        working_hours: float = 3890.0,
        top_n: int = 5,
    ) -> List[Dict[str, Any]]:
        """Подобрать установки под одну операцию отделения.

        Args:
            operation: ключ позиции (``OPERATION_TITLES``)
            quantity: годовой объём работы: м3/год (unit='m3_h') или
                т/год (unit='t_h') — единица берётся из карточки
            material_category: категория сплава ('steel'/'cast_iron'/'aluminum')
            working_hours: действительный годовой фонд времени, ч
            top_n: сколько лучших вариантов вернуть

        Returns:
            Карточки, отсортированные от наиболее оптимальных, с ключами
            ``_score``, ``_num_required``, ``_units``, ``_load_factor``,
            ``_quantity``
        """
        candidates: List[Dict[str, Any]] = []
        if quantity <= 0 or working_hours <= 0:
            return candidates
        for machine in self._all_mixers():
            if machine.get("operation") != operation:
                continue
            app = machine.get("applicable_for", {})
            materials = app.get("materials", [])
            if materials and material_category not in materials:
                continue
            q = machine_productivity(machine)
            if q <= 0:
                continue
            n_req = quantity * K_UNEVEN / (q * working_hours)
            units = pick_unit_count(n_req)
            lf = load_factor(n_req, units)
            score = self._score_machine(machine, n_req, units, lf)
            unit_label = UNIT_LABELS.get(machine.get("unit", "m3_h"), "")
            candidates.append({
                **machine,
                "_score": score,
                "_num_required": round(n_req, 2),
                "_units": units,
                "_load_factor": lf,
                "_quantity": round(quantity, 1),
                "card_fields": [
                    ("batch_volume_m3", "Объём замеса, м³"),
                    ("productivity_m3_h", f"Произв., {unit_label}"),
                    ("productivity_t_h", f"Произв., {unit_label}"),
                    ("installed_power_kw", "Мощность, кВт"),
                    ("mass_kg", "Масса, кг"),
                ],
            })
        candidates.sort(key=lambda x: x["_score"], reverse=True)
        return candidates[:top_n]

    # ---------- сводный расчёт отделения ----------
    def calc_department(
        self,
        annual_output_t: float,
        annual_molds: int,
        mold_volume_m3: float,
        metal_per_mold_kg: float,
        cores_per_mold: float = DEFAULT_CORES_PER_MOLD,
        avg_core_mass_kg: float = 0.0,
        material_category: str = "steel",
        working_hours: float = 3890.0,
        tamped_density: float = DENSITY_TAMPED_PRESS,
        lumps_share: float = LUMPS_SHARE_DEFAULT,
        top_n: int = 5,
        selected_ids: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Рассчитать все позиции смесеприготовительного отделения.

        Годовой объём стержневой смеси: масса стержней программы
        (Nст.год · m_стерж) делится на плотность ГТС. Формовочная смесь —
        по геометрии форм (:func:`calc_sand_volumes`). Регенерация:
        просев/охлаждение/сепарация работают с полным объёмом оборота
        формовочной смеси (неуплотнённой), дробилка — с долей комьев по
        массе.

        Args:
            annual_output_t: годовой выпуск годного литья, т (справочно)
            annual_molds: годовое число форм, шт
            mold_volume_m3: объём одной опки в свету, м3
            metal_per_mold_kg: средняя масса металла в форме с ЛПС, кг
            cores_per_mold: среднее число стержней на форму
            avg_core_mass_kg: средняя масса одного стержня, кг (0 — типовой 3 кг)
            material_category: категория сплава проекта
            working_hours: действительный годовой фонд времени оборудования
            tamped_density: плотность уплотнённой смеси в форме, т/м3
            lumps_share: доля комьев в обороте смеси для дробилки
            top_n: сколько вариантов показывать по каждой позиции
            selected_ids: сохранённый выбор пользователя {operation: id}

        Returns:
            Словарь с ``volumes`` (расход смеси), ``operations`` (позиции с
            options/selected_id/units/load_factor) и ``summary`` (тоннаж,
            парк, средний Кзо)
        """
        selected_ids = dict(selected_ids or {})
        core_mass = avg_core_mass_kg if avg_core_mass_kg > 0 \
            else AVG_CORE_MASS_KG
        annual_cores = int(math.ceil(annual_molds * cores_per_mold))
        cores_mass_t = annual_cores * core_mass / 1000.0

        volumes = calc_sand_volumes(
            annual_molds=annual_molds,
            mold_volume_m3=mold_volume_m3,
            metal_per_mold_kg=metal_per_mold_kg,
            cores_mass_per_mold_kg=cores_per_mold * core_mass,
            tamped_density=tamped_density,
        )
        molding_loose_m3 = volumes["sand_volume_loose_m3"]
        molding_mass_t = volumes["sand_mass_tamped_t"]
        # Диплом 2: объём стержневой смеси = масса / ρГТС · (1.55/1.1).
        core_mix_m3 = cores_mass_t / DENSITY_GTS * CORE_MIX_FACTOR
        lumps_mass_t = molding_mass_t * lumps_share

        quantities: Dict[str, float] = {
            "molding_mix": molding_loose_m3,
            "core_mix": core_mix_m3,
            "lumps": lumps_mass_t,
            "sieving": molding_loose_m3,
            "cooling": molding_loose_m3,
            "magnetic_separation": molding_loose_m3,
        }

        operations: List[Dict[str, Any]] = []
        park_units: int = 0
        lf_sum = 0.0
        lf_cnt = 0
        for op in OPERATION_ORDER:
            qty = quantities.get(op, 0.0)
            options = self.find_for_operation(
                operation=op, quantity=qty,
                material_category=material_category,
                working_hours=working_hours, top_n=top_n,
            )
            chosen_id = ""
            saved = selected_ids.get(op, "")
            if saved and any(o.get("id") == saved for o in options):
                chosen_id = saved
            elif options:
                chosen_id = options[0].get("id", "")
            chosen = next((o for o in options if o.get("id") == chosen_id), {})
            units = int(chosen.get("_units", 0))
            lf = float(chosen.get("_load_factor", 0.0))
            park_units += units
            if units > 0:
                lf_sum += lf
                lf_cnt += 1
            operations.append({
                "operation": op,
                "title": OPERATION_TITLES.get(op, op),
                "quantity": round(qty, 1),
                "quantity_unit": UNIT_LABELS.get(
                    chosen.get("unit", "m3_h"), "м³") if chosen else "—",
                "options": options,
                "selected_id": chosen_id,
                "units": units,
                "load_factor": lf,
                "n_required": float(chosen.get("_num_required", 0.0)),
                "model_name": chosen.get("name", ""),
            })

        summary = {
            "annual_output_t": round(annual_output_t, 1),
            "annual_molds": annual_molds,
            "annual_cores": annual_cores,
            "cores_mass_t": round(cores_mass_t, 1),
            "total_park_units": park_units,
            "avg_load_factor": round(lf_sum / lf_cnt, 3) if lf_cnt else 0.0,
            "working_hours": working_hours,
            "k_uneven": K_UNEVEN,
        }
        return {
            "volumes": {**volumes,
                        "core_mix_m3": round(core_mix_m3, 1),
                        "lumps_mass_t": round(lumps_mass_t, 1)},
            "operations": operations,
            "summary": summary,
        }


def to_picker_options(options: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Преобразовать карточки установок в формат ``EquipmentPicker``.

    Args:
        options: карточки из :meth:`SandPrepCalculator.find_for_operation`

    Returns:
        Список словарей с ``id``, ``name``, ``capacity``, ``productivity``,
        ``power``, ``count``, ``load_factor`` и прочими полями виджета
    """
    result: List[Dict[str, Any]] = []
    for o in options:
        specs = o.get("specs", {})
        unit = o.get("unit", "m3_h")
        prod = machine_productivity(o)
        prod_min = float(specs.get(
            "productivity_min_t_h" if unit == "t_h"
            else "productivity_min_m3_h", 0) or 0)
        prod_txt = f"{prod:g} {UNIT_LABELS.get(unit, '')}"
        if prod_min > 0 and abs(prod - prod_min) > 1e-9:
            prod_txt = f"{prod_min:g}–{prod:g} {UNIT_LABELS.get(unit, '')}"
        batch = float(specs.get("batch_volume_m3", 0) or 0)
        result.append({
            "id": o.get("id", ""),
            "name": o.get("name", ""),
            "type": o.get("type", ""),
            "description": o.get("description", ""),
            "capacity": f"{batch:g} м³" if batch > 0 else "—",
            "productivity": prod_txt,
            "power": f"{float(specs.get('installed_power_kw', 0) or 0):g} кВт"
                     if specs.get("installed_power_kw") else "—",
            "count": o.get("_units", 0),
            "load_factor": o.get("_load_factor", 0.0),
            "n_required": o.get("_num_required", 0.0),
            "recommended": bool(
                o.get("applicable_for", {}).get("recommended", False)),
            "custom": bool(o.get("custom", False)),
        })
    return result


def get_chosen_operations(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Вернуть только выбранные позиции отделения (для сводки/сохранения).

    Args:
        result: вывод :meth:`SandPrepCalculator.calc_department`

    Returns:
        Список позиций с ``operation``, ``selected_id``, ``model_name``,
        ``units``, ``load_factor``
    """
    return [
        {
            "operation": op["operation"],
            "title": op["title"],
            "selected_id": op["selected_id"],
            "model_name": op["model_name"],
            "units": op["units"],
            "load_factor": op["load_factor"],
            "quantity": op["quantity"],
            "quantity_unit": op["quantity_unit"],
        }
        for op in result.get("operations", [])
        if op.get("selected_id")
    ]


def calc_sand_prep(
    project: Any,
    calculator: Optional[SandPrepCalculator] = None,
    selected_ids: Optional[Dict[str, str]] = None,
    top_n: int = 5,
) -> Dict[str, Any]:
    """Единая точка расчёта смесеприготовления для GUI.

    Берёт данные из модели ``Project`` (годовое число форм, объём опки,
    средняя масса металла в форме, категория сплава, фонд времени) и
    возвращает результат :meth:`SandPrepCalculator.calc_department`.

    Args:
        project: модель ``Project``
        calculator: калькулятор (по умолчанию создаётся новый)
        selected_ids: сохранённый выбор пользователя {operation: id}
        top_n: сколько вариантов показывать по каждой позиции

    Returns:
        Результат ``calc_department``
    """
    from core.molding import calc_avg_cores_per_mold  # локально, без цикла

    calc = calculator or SandPrepCalculator()
    castings: List[Any] = list(getattr(project, "castings", []) or [])
    annual_molds = sum(int(getattr(c, "molds_per_year", 0) or 0)
                       for c in castings)
    mold_weights = annual_molds or 1
    if castings:
        metal_per_mold = sum(
            float(getattr(c, "mass_with_LPS_kg", 0.0) or 0.0)
            * int(getattr(c, "molds_per_year", 0) or 0)
            for c in castings) / mold_weights
        cores_per_mold = calc_avg_cores_per_mold(castings)
    else:
        metal_per_mold = 0.0
        cores_per_mold = DEFAULT_CORES_PER_MOLD

    # Объём опки и масса стержней — взвешенные средние по программе формовки;
    # если у позиций данных нет — типовые оценки (как в дипломах).
    mold_volume = float(getattr(project, "mold_volume_m3", 0.0) or 0.0)
    if mold_volume <= 0 and castings:
        mold_volume = sum(_flask_volume_m3(c) * int(
            getattr(c, "molds_per_year", 0) or 0) for c in castings
        ) / mold_weights
    if mold_volume <= 0:
        # Типовая оценка, если проект не задаёт объём опки явно: форма ≈
        # 2.5× объёма залитого уплотнённого металла (среднее по АФЛ).
        mold_volume = (max(metal_per_mold, 1.0) / 1000.0 * 2.5
                       / DENSITY_TAMPED_SHAKE if metal_per_mold > 0 else 0.216)

    avg_core_mass = float(getattr(project, "avg_core_mass_kg", 0.0) or 0.0)
    if avg_core_mass <= 0 and castings:
        total_cores = sum(int(getattr(c, "cores_count", 0) or 0) * int(
            getattr(c, "molds_per_year", 0) or 0) for c in castings)
        total_core_mass = sum(float(getattr(c, "core_mass_kg", 0.0) or 0.0) * int(
            getattr(c, "molds_per_year", 0) or 0) for c in castings)
        if total_cores > 0:
            avg_core_mass = total_core_mass / total_cores

    category = _alloy_category(str(getattr(project, "selected_alloy_id", "")))
    fund = float(getattr(project, "F_equipment_sand_h", 0.0) or
                 getattr(project, "F_equipment_h", 3890.0) or 3890.0)

    return calc.calc_department(
        annual_output_t=float(getattr(project, "annual_output_t", 0.0) or 0.0),
        annual_molds=annual_molds,
        mold_volume_m3=mold_volume,
        metal_per_mold_kg=metal_per_mold,
        cores_per_mold=cores_per_mold,
        avg_core_mass_kg=avg_core_mass,
        material_category=category,
        working_hours=fund,
        top_n=top_n,
        selected_ids=selected_ids,
    )


def _flask_volume_m3(item: Any) -> float:
    """Оценить объём опки позиции в свету, м³, по строке ``flask_size_mm``.

    Поддерживает формат «900x600x200/200» (длина×ширина×высота верхней/нижней
    полуформы) и «ØNNNxH» для круглых опок. Берётся полная высота (верх+низ).

    Args:
        item: позиция номенклатуры (CastingItem или совместимый объект)

    Returns:
        Объём опки, м³; 0.0, если строку размера разобрать не удалось
    """
    raw = str(getattr(item, "flask_size_mm", "") or "").strip().lower()
    if not raw:
        return 0.0
    try:
        if raw.startswith("ø") or raw.startswith("d"):
            parts = raw.lstrip("ød").split("x")
            diam = float(parts[0])
            height = float(parts[1]) if len(parts) > 1 else diam / 2.0
            return math.pi * (diam / 2000.0) ** 2 * (height / 1000.0)
        parts = raw.replace("+", "/").split("/")
        dims = [float(p) for p in parts[0].split("x") if p]
        if len(dims) < 3:
            return 0.0
        length, width, height = dims[0], dims[1], dims[2]
        if len(parts) > 1 and parts[1]:
            height += float(parts[1])  # верхняя + нижняя полуформы
        return length * width * height / 1e9
    except (ValueError, IndexError):
        return 0.0


def _alloy_category(alloy_id: str) -> str:
    """Определить категорию материала по ``selected_alloy_id``.

    Args:
        alloy_id: идентификатор сплава из alloys.json

    Returns:
        'steel' / 'cast_iron' / 'aluminum'; при неизвестном id — 'steel'
    """
    try:
        loader = DataLoader(DATA_DIR)
        cat = loader.get_alloy_category(alloy_id)
        if cat:
            return str(cat)
    except Exception:
        pass
    return "steel"
