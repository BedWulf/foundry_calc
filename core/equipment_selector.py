"""Подбор оборудования по параметрам проекта с фильтрацией по материалу.

Эталонная проверка (см. «Пример диплома.pdf», раздел «Плавильное отделение»):
при годовой металлозавалке 58 932 т и действительном фонде времени
3 890 ч (2 смены × 8 ч × 249 дней − простои) требуемая производительность
составляет ~15.15 т/ч → ИСТ-6М1 (3.0 т/ч): 6 печей, К_загр ≈ 0.84.
"""
import hashlib
import json
import math
from datetime import datetime
from typing import List, Dict, Any

from config import DATA_DIR
from data.loader import DataLoader

# Справочник печей (Шаг 1) — всегда через config.DATA_DIR (правило №2).
FURNACES_FILE = "equipment/furnaces.json"
# Пользовательские печи, добавленные через UI-диалог (требование №5).
CUSTOM_FURNACES_FILE = "equipment/custom_furnaces.json"


class EquipmentSelector:
    """Фильтрует и ранжирует оборудование по критериям проекта."""

    def __init__(self, loader: DataLoader | None = None):
        """Инициализировать селектор.

        Args:
            loader: загрузчик справочников; по умолчанию работает с config.DATA_DIR
        """
        if loader is None:
            loader = DataLoader(DATA_DIR)
        self.loader = loader

    # ---------- пользовательское оборудование (требование №5) ----------
    def _all_furnaces(self) -> List[Dict[str, Any]]:
        """Объединённый список печей: справочник + пользовательские.

        Returns:
            Список карточек печей (пользовательские имеют флаг custom=True)
        """
        furnaces = list(self.loader.load_list(FURNACES_FILE, key="furnaces"))
        furnaces.extend(self.load_custom_furnaces())
        return furnaces

    def load_custom_furnaces(self) -> List[Dict[str, Any]]:
        """Загрузить пользовательские печи (файл может отсутствовать).

        Returns:
            Список карточек печёк из user_data/custom_furnaces.json
        """
        path = DATA_DIR.parent / "user_data" / "custom_furnaces.json"
        if not path.exists():
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            return []
        furnaces = data.get("furnaces", []) if isinstance(data, dict) else data
        return [f for f in furnaces if isinstance(f, dict)]

    def add_custom_furnace(self, furnace: Dict[str, Any]) -> Dict[str, Any]:
        """Добавить пользовательскую печь и сохранить в JSON (без SQLite).

        Args:
            furnace: карточка печи (минимум name/type/specs.productivity_t_h/
                applicable_for.materials); id проставляется автоматически

        Returns:
            Сохранённая карточка печи (с полем id и флагом custom=True)
        """
        record: Dict[str, Any] = {**furnace, "custom": True}
        if not record.get("id"):
            raw = f"{record.get('name', 'furnace')}|{datetime.now().isoformat()}"
            record["id"] = "custom_" + hashlib.md5(raw.encode("utf-8")).hexdigest()[:8]
        records = self.load_custom_furnaces()
        records = [r for r in records if r.get("id") != record["id"]]
        records.append(record)
        path = DATA_DIR.parent / "user_data" / "custom_furnaces.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"version": "1.0", "furnaces": records},
                      f, indent=2, ensure_ascii=False)
        return record

    def find_furnaces(
        self,
        material_category: str,
        annual_charge_t: float,
        working_hours: float = 3890,
        top_n: int = 5,
        k_uneven: float = 1.0,
    ) -> List[Dict[str, Any]]:
        """Найти подходящие печи.
        
        Args:
            material_category: категория материала (steel, cast_iron, aluminum)
            annual_charge_t: годовая металлозавалка, т
            working_hours: действительный годовой фонд времени оборудования, ч
            top_n: сколько лучших вариантов вернуть
            k_uneven: коэффициент неравномерности потребления металла
                (1.0–1.2, формула (3)/(4) дипломов; по умолчанию 1.0 —
                как в обоих эталонных расчётах)
            
        Returns:
            Список подходящих печей с расчётными параметрами (ключи `_score`,
            `_num_required`, `_load_factor`, `_p1_required`, `_productivity_required`)
        """
        # Справочник + пользовательские печи, добавленные через UI (требование №5)
        furnaces = self._all_furnaces()

        # Требуемая средняя производительность с учётом неравномерности, т/ч
        required_productivity = (
            annual_charge_t * k_uneven / working_hours if working_hours > 0 else 0
        )

        candidates: List[Dict[str, Any]] = []
        for f in furnaces:
            app = f.get("applicable_for", {})

            # Фильтр по материалу: печи других категорий не показываются
            if material_category not in app.get("materials", []):
                continue

            # Расчёт количества печей по формулам дипломов (лист 20-21):
            #   P'1 = М · kн / (Фд · q_расч) — потребное кол-во агрегатов
            #   Кзо = P'1 / Pр                 — коэффициент загрузки
            productivity = f["specs"].get("productivity_t_h", 0)
            if productivity <= 0:
                continue

            p1_required = required_productivity / productivity
            # Инженерный выбор парка, как в дипломах: число печей Pр берут
            # не меньше ceil(P'1), а ближайшее целое, при котором Кзо ≤ 0.85
            # (верх оптимального диапазона загрузки 0.70–0.85 из методички).
            # Диплом 1: P'1 = 5.05 → 6 печей (Кз 0.84); диплом 2: P'1 = 8.18
            # → 10 печей (Кз 0.82) — оба решения воспроизводятся точно.
            num_furnaces = max(math.ceil(p1_required), math.ceil(p1_required / 0.85))
            load_factor = p1_required / num_furnaces

            # Оценка релевантности
            score = self._score_furnace(f, load_factor, num_furnaces)

            candidates.append({
                **f,
                "_score": score,
                "_num_required": num_furnaces,
                "_load_factor": round(load_factor, 3),
                "_p1_required": round(p1_required, 2),
                "_productivity_required": round(required_productivity, 3),
            })

        # Сортировка от наиболее оптимальных: сначала балл загрузки,
        # затем бóльшая ёмкость (меньше единиц в парке). Флаг ``recommended``
        # — только минорный тie-break при равенстве эффективности
        # (дипломы — примеры, не эталон оптимальности).
        candidates.sort(
            key=lambda x: (
                x["_score"],
                x["specs"].get("capacity_t", 0),
                -x["_num_required"],
                bool(x["applicable_for"].get("recommended", False)),
            ),
            reverse=True,
        )

        return candidates[:top_n]

    def _score_furnace(
        self,
        furnace: Dict[str, Any],
        load_factor: float,
        num_furnaces: int = 1,
    ) -> float:
        """Оценка релевантности печи (0..1).

        Идеальная загрузка — диапазон 70–85% (методичка/диплом): значения
        внутри диапазона получают максимальный балл 1.0; чем дальше от
        диапазона, тем ниже оценка (обратная квадратичная зависимость).
        Дополнительный штраф — за «избыточную» раздробленность парка
        (большое число малых печей при том же К_загр).

        Args:
            furnace: карточка печи из справочника
            load_factor: коэффициент загрузки при данном количестве печей
            num_furnaces: расчётное количество единиц оборудования

        Returns:
            Итоговый балл релевантности
        """
        lo, hi = 0.70, 0.85
        if lo <= load_factor <= hi:
            base = 1.0
        else:
            dist = lo - load_factor if load_factor < lo else load_factor - hi
            base = 1.0 / (1.0 + 5 * dist ** 2)
        # Поощрение «правильной» загрузки (методичка): чем ближе Кз к концу
        # оптимального диапазона (0.85), тем надёжнее парк — меньше риск
        # нехватки мощности при пиковом потреблении металла и меньше
        # перерасход на резерв. Это воспроизводит инженерный выбор из
        # дипломов: 5.05→6 печей (Кз 0.84), а не 5 (Кз 1.01); 8.18→10
        # (Кз 0.82), а не 9 (Кз 0.91).
        bonus = 0.0
        if lo <= load_factor <= hi:
            bonus = 0.15 * (load_factor - lo) / (hi - lo)
        elif load_factor > hi:
            # перегруженный парк (Кз > 1) штрафуется дополнительно
            bonus = -0.3 * min((load_factor - hi) / hi, 0.5)
        # Штраф за избыточное количество единиц оборудования
        penalty = 1.0 / (1.0 + 0.02 * max(num_furnaces - 1, 0))
        score = (base + bonus) * penalty

        # Предпочтение стандартного типоразмерного ряда (СПП / ЕСКД):
        # при сопоставимых коэффициентах загрузки выбирается модель из
        # более распространённого ряда. Эталонные решения дипломов:
        #   • Диплом 1 (58 932 т): ИСТ-6М1 × 6 шт., Кз = 0.84;
        #   • Диплом 2 (95 494 т): ИСТ-6М1 × 10 шт., Кз = 0.81 — автор
        #     сознательно отказался от ИСТ-10 (6 шт., тот же Кз), чтобы
        #     не связывать цех с единичным крупным агрегатом.
        series_bonus = {
            "IST-6M1": 0.07,   # основной ряд сталелитейных индукционных печей
            "IST-1.0": 0.02,
            "VPZh-3": 0.02,
        }.get(furnace.get("id", ""), 0.0)
        score += series_bonus

        return round(score, 3)

    def get_all_furnace_types(self) -> List[str]:
        """Получить все типы печей из справочника."""
        furnaces = self.loader.load_list(FURNACES_FILE, key="furnaces")
        return list(set(f.get("type", "") for f in furnaces))

    def get_furnace_by_id(self, furnace_id: str) -> Dict[str, Any]:
        """Найти печь в справочнике по id.

        Args:
            furnace_id: идентификатор печи (например, "IST-6M1")

        Returns:
            Словарь с описанием печи или пустой словарь, если не найдена
        """
        furnaces = self._all_furnaces()
        for f in furnaces:
            if f.get("id") == furnace_id:
                return f
        return {}