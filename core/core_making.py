"""Расчёт стержневого отделения: программа стержней и подбор машин.

Эталонные формулы (методичка, раздел «Стержневое отделение»; дипломы):

    Nст.год = Σ (Г_i · k_бр.доп / m_отл,i) · n_ст,i     — годовое число стержней
    Q_ч     = 3600 / t_цикл · N_гнёзд                   — произв. машины, ст/ч
    L       = Nст.год / Q_ч                             — машино-часы в год
    Ппр     = ceil(L / Фд)                              — принятое число машин
    Кзо     = L / (Ппр · Фд)                            — коэффициент загрузки

В отличие от печей, парк стержневых машин рассматривается как пул часов:
сколько машино-часов ``L`` требует программа — столько и нужно покрыть
машинами выбранной модели при фонде времени ``Фд``.

Справочник: ``data/equipment/core_machines.json`` (ключ ``machines``).
Пользовательские машины: ``user_data/custom_core_machines.json``.
"""
import hashlib
import json
import math
from datetime import datetime
from typing import Any, Dict, List, Optional

from config import DATA_DIR, USER_DATA_DIR
from data.loader import DataLoader

#: Справочник стержневого оборудования — только через DATA_DIR.
CORE_MACHINES_FILE = "equipment/core_machines.json"

#: Идеальная зона загрузки парка (методичка, 0.70–0.85)
LOAD_OPTIMAL_MIN: float = 0.70
LOAD_OPTIMAL_MAX: float = 0.85

#: Среднее число стержней в форме, если номенклатура не задана (методичка)
DEFAULT_CORES_PER_MOLD: float = 1.5


def core_counts_complete(castings, *, zeros_confirmed: bool = False) -> bool:
    """True when every productive casting's core count can be trusted.

    A positive number is explicit. The legacy field default (zero) is
    ambiguous until the user confirms that all zero rows really are
    coreless. Empty/invalid molding programs are not confirmed.
    """
    productive = [c for c in castings
                  if int(getattr(c, "molds_per_year", 0) or 0) > 0]
    if not productive:
        return False
    return all(
        int(getattr(c, "cores_count", 0) or 0) > 0
        or (bool(getattr(c, "cores_count_verified", False))
            and bool(str(getattr(c, "cores_count_source", "")).strip()))
        or zeros_confirmed
        for c in productive
    )


def calc_annual_cores(annual_molds: int, cores_per_mold: float) -> int:
    """Годовое количество стержней по программе формовки.

    Args:
        annual_molds: годовое число форм, шт
        cores_per_mold: среднее число стержней на одну форму

    Returns:
        Годовое число стержней, шт (округление вверх); 0 при некорректных данных
    """
    if annual_molds <= 0 or cores_per_mold <= 0:
        return 0
    return int(math.ceil(annual_molds * cores_per_mold))


def machine_hourly_output(machine: Dict[str, Any]) -> float:
    """Часовая производительность стержневой машины, стержней/час.

    Берётся из паспорта ``specs.hourly_output_cores_h``; если поля нет —
    считается по циклу: ``3600 / cycle_time_s * cavities_per_box``.

    Args:
        machine: карточка машины из справочника

    Returns:
        Производительность, ст/ч (0, если данных недостаточно)
    """
    specs = machine.get("specs", {})
    direct = float(specs.get("hourly_output_cores_h", 0) or 0)
    if direct > 0:
        return direct
    cycle = float(specs.get("cycle_time_s", 0) or 0)
    cavities = float(specs.get("cavities_per_box", 0) or 0)
    if cycle > 0 and cavities > 0:
        return 3600.0 / cycle * cavities
    return 0.0


def calc_park_load(annual_cores: int, hourly_output: float,
                   fund_hours: float) -> Dict[str, Any]:
    """Рассчитать загрузку парка машин выбранной модели.

    Args:
        annual_cores: годовая программа стержней, шт
        hourly_output: часовая производительность одной машины, ст/ч
        fund_hours: действительный фонд времени оборудования, ч

    Returns:
        Словарь: ``hours_required`` (машино-часы, ч), ``num_machines``
        (ceil от L/Фд, шт), ``load_factor`` (Кзо при принятом количестве)
    """
    if hourly_output <= 0 or annual_cores <= 0 or fund_hours <= 0:
        return {"hours_required": 0.0, "num_machines": 0, "load_factor": 0.0}
    hours = annual_cores / hourly_output
    num = max(1, math.ceil(hours / fund_hours))
    load = hours / (num * fund_hours)
    return {"hours_required": round(hours, 1), "num_machines": num,
            "load_factor": round(load, 3)}


class CoreCalculator:
    """Подбор стержневых машин под годовую программу с фильтром по материалу."""

    def __init__(self, loader: Optional[DataLoader] = None):
        """Инициализировать калькулятор.

        Args:
            loader: загрузчик справочников (по умолчанию — config.DATA_DIR)
        """
        self.loader = loader or DataLoader(DATA_DIR)

    # ---------- справочник + пользовательские машины ----------
    def _all_machines(self) -> List[Dict[str, Any]]:
        """Объединённый список машин: справочник + пользовательские."""
        machines = list(self.loader.load_list(CORE_MACHINES_FILE, key="machines"))
        machines.extend(self.load_custom_machines())
        return machines

    @staticmethod
    def custom_path() -> Any:
        """Путь к файлу пользовательских стержневых машин."""
        return USER_DATA_DIR / "custom_core_machines.json"

    def load_custom_machines(self) -> List[Dict[str, Any]]:
        """Загрузить пользовательские машины (файл может отсутствовать)."""
        path = self.custom_path()
        if not path.exists():
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            return []
        machines = data.get("machines", []) if isinstance(data, dict) else data
        return [m for m in machines if isinstance(m, dict)]

    def add_custom_machine(self, machine: Dict[str, Any]) -> Dict[str, Any]:
        """Добавить пользовательскую стержневую машину и сохранить в JSON.

        Args:
            machine: карточка (name/type/specs.cycle_time_s +
                cavities_per_box/applicable_for.materials); id проставляется
                автоматически, часовая производительность досчитывается

        Returns:
            Сохранённая карточка с полями ``id`` и ``custom=True``
        """
        record: Dict[str, Any] = {**machine, "custom": True}
        if not record.get("id"):
            raw = f"{record.get('name', 'core')}|{datetime.now().isoformat()}"
            record["id"] = "custom_" + hashlib.md5(raw.encode("utf-8")).hexdigest()[:8]
        specs = dict(record.get("specs", {}))
        if float(specs.get("hourly_output_cores_h", 0) or 0) <= 0:
            specs["hourly_output_cores_h"] = round(machine_hourly_output(record), 1)
        record["specs"] = specs
        records = [r for r in self.load_custom_machines()
                   if r.get("id") != record["id"]]
        records.append(record)
        path = self.custom_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"version": "1.0", "machines": records}, f,
                      indent=2, ensure_ascii=False)
        return record

    # ---------- скоринг ----------
    @staticmethod
    def _score_machine(machine: Dict[str, Any], load_factor: float,
                       num_machines: int = 1) -> float:
        """Балл релевантности машины (чем выше, тем лучше).

        Оптимальна загрузка парка 0.70–0.85: внутри зоны балл ~1.0,
        чем дальше — тем ниже. При перегруженном парке (после округления
        числа машин вверх Кзо у всех моделей ≈ 1 и различить их нельзя)
        вариант различают штрафом за раздробленность: меньше машин в парке
        — дешевле содержание. Для недогруженного/оптимального парка малый
        бонус даёт высокая часовая производительность.

        Args:
            machine: карточка машины
            load_factor: рассчитанный Кзо парка
            num_machines: принятое число машин (ceil от L/Фд)

        Returns:
            Балл 0..~1.2
        """
        if load_factor <= 0:
            return -1.0
        if LOAD_OPTIMAL_MIN <= load_factor <= LOAD_OPTIMAL_MAX:
            base = 1.0
        elif load_factor < LOAD_OPTIMAL_MIN:
            base = max(0.0, 1.0 - (LOAD_OPTIMAL_MIN - load_factor) * 2.5)
        else:
            base = max(0.0, 1.0 - (load_factor - LOAD_OPTIMAL_MAX) * 4.0)
        if load_factor > LOAD_OPTIMAL_MAX:
            # Парк перегружен после округления вверх: все модели дают почти
            # одинаковый Кзо, выбираем наименьшее количество машин.
            fragmentation_penalty = 0.1 * max(num_machines - 1, 0)
            return base - min(fragmentation_penalty, 0.5)
        prod_bonus = min(0.2, machine_hourly_output(machine) / 6000.0)
        return base + prod_bonus

    # ---------- подбор ----------
    def find_machines(
        self,
        material_category: str,
        annual_cores: int,
        working_hours: float = 3890.0,
        max_casting_mass_kg: float = 0.0,
        top_n: int = 5,
    ) -> List[Dict[str, Any]]:
        """Подобрать подходящие стержневые машины.

        Args:
            material_category: категория сплава ('steel'/'cast_iron'/'aluminum')
            annual_cores: годовая программа стержней, шт
            working_hours: действительный фонд времени оборудования, ч
            max_casting_mass_kg: наибольшая масса отливки с ЛПС, кг
                (фильтр по диапазону ящика; 0 — без фильтра)
            top_n: сколько лучших вариантов вернуть

        Returns:
            Карточки машин, отсортированные от наиболее оптимальных, с
            расчётными ключами ``_score``, ``_num_required``,
            ``_load_factor``, ``_hours_required``, ``_cores_required``
        """
        candidates: List[Dict[str, Any]] = []
        for machine in self._all_machines():
            app = machine.get("applicable_for", {})
            if material_category not in app.get("materials", []):
                continue
            mass_range = app.get("casting_mass_range_kg") or [0, 0]
            if max_casting_mass_kg > 0 and max_casting_mass_kg > float(mass_range[1]):
                continue
            hourly = machine_hourly_output(machine)
            if hourly <= 0:
                continue

            res = calc_park_load(annual_cores, hourly, working_hours)
            score = self._score_machine(machine, res["load_factor"],
                                        res["num_machines"])
            candidates.append({
                **machine,
                "_score": score,
                "_num_required": res["num_machines"],
                "_load_factor": res["load_factor"],
                "_hours_required": res["hours_required"],
                "_cores_required": annual_cores,
                "card_fields": [
                    ("box_size_mm", "Ящик"),
                    ("cycle_time_s", "Цикл, с"),
                    ("cavities_per_box", "Гнезд"),
                    ("hourly_output_cores_h", "Производительность, ст/ч"),
                ],
            })

        # Сортировка от наиболее оптимальных: балл загрузки → выше часовая
        # производительность (меньше машин в парке) → меньше машин.
        # ``recommended`` — лишь минорный tie-break (дипломы — примеры).
        candidates.sort(
            key=lambda x: (
                x["_score"],
                machine_hourly_output(x),
                -x["_num_required"],
                bool(x.get("applicable_for", {}).get("recommended", False)),
            ),
            reverse=True,
        )
        return candidates[:top_n]

    def calc_cores(
        self,
        material_category: str,
        annual_molds: int,
        cores_per_mold: float = DEFAULT_CORES_PER_MOLD,
        working_hours: float = 3890.0,
        max_casting_mass_kg: float = 0.0,
        top_n: int = 5,
        selected_machine_id: Optional[str] = None,
        exact_annual_cores: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Связка «формовка → стержни»: программа стержней и подбор машин.

        Args:
            material_category: категория сплава проекта
            annual_molds: годовое число форм (из формовочного отделения)
            cores_per_mold: среднее число стержней на форму
            working_hours: действительный фонд времени оборудования, ч
            max_casting_mass_kg: наибольшая масса отливки с ЛПС, кг
            top_n: сколько лучших вариантов вернуть
            selected_machine_id: сохранённый выбор пользователя; если машина
                больше не подходит — берётся лучший вариант по скорингу

        Returns:
            Словарь: ``annual_cores``, ``cores_per_mold``, ``options``
            (отсортированные карточки), ``selected_machine_id``,
            ``machine_count``, ``load_factor``, ``hours_required``
        """
        if exact_annual_cores is not None:
            if type(exact_annual_cores) is not int or exact_annual_cores < 0:
                raise ValueError("Точное годовое количество стержней должно быть неотрицательным целым")
            annual_cores = exact_annual_cores
        else:
            annual_cores = calc_annual_cores(annual_molds, cores_per_mold)
        options = self.find_machines(
            material_category=material_category,
            annual_cores=annual_cores,
            working_hours=working_hours,
            max_casting_mass_kg=max_casting_mass_kg,
            top_n=top_n,
        )
        chosen_id = ""
        if selected_machine_id and any(
                o.get("id") == selected_machine_id for o in options):
            chosen_id = selected_machine_id
        elif options:
            chosen_id = options[0].get("id", "")
        chosen = next((o for o in options if o.get("id") == chosen_id), {})
        return {
            "annual_cores": annual_cores,
            "cores_per_mold": cores_per_mold,
            "options": options,
            "selected_machine_id": chosen_id,
            "machine_count": int(chosen.get("_num_required", 0)),
            "load_factor": float(chosen.get("_load_factor", 0.0)),
            "hours_required": float(chosen.get("_hours_required", 0.0)),
        }
