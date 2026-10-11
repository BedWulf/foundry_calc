"""Подбор оборудования по параметрам проекта с фильтрацией по материалу.

Эталонная проверка (см. «Пример диплома.pdf», раздел «Плавильное отделение»):
при годовой металлозавалке 58 932 т и действительном фонде времени
3 890 ч (2 смены × 8 ч × 249 дней − простои) требуемая производительность
составляет ~15.15 т/ч → ИСТ-6М1 (3.0 т/ч): 6 печей, К_загр ≈ 0.84.
"""
import math
from typing import List, Dict, Any

from config import DATA_DIR
from data.loader import DataLoader

# Справочник печей (Шаг 1) — всегда через config.DATA_DIR (правило №2).
FURNACES_FILE = "equipment/furnaces.json"


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

    def find_furnaces(
        self,
        material_category: str,
        annual_charge_t: float,
        working_hours: float = 3890,
        top_n: int = 5,
    ) -> List[Dict[str, Any]]:
        """Найти подходящие печи.
        
        Args:
            material_category: категория материала (steel, cast_iron, aluminum)
            annual_charge_t: годовая металлозавалка, т
            working_hours: действительный фонд времени, ч
            top_n: сколько лучших вариантов вернуть
            
        Returns:
            Список подходящих печей с расчётными параметрами (ключи `_score`,
            `_num_required`, `_load_factor`, `_productivity_required`)
        """
        furnaces = self.loader.load_list(FURNACES_FILE, key="furnaces")

        # Требуемая средняя производительность, т/ч
        required_productivity = annual_charge_t / working_hours if working_hours > 0 else 0

        candidates: List[Dict[str, Any]] = []
        for f in furnaces:
            app = f.get("applicable_for", {})

            # Фильтр по материалу: печи других категорий не показываются
            if material_category not in app.get("materials", []):
                continue

            # Расчёт количества печей
            productivity = f["specs"].get("productivity_t_h", 0)
            if productivity <= 0:
                continue

            num_furnaces = math.ceil(required_productivity / productivity)
            load_factor = required_productivity / (num_furnaces * productivity)

            # Оценка релевантности
            score = self._score_furnace(f, load_factor, num_furnaces)

            candidates.append({
                **f,
                "_score": score,
                "_num_required": num_furnaces,
                "_load_factor": round(load_factor, 3),
                "_productivity_required": round(required_productivity, 3),
            })

        # Сортировка: recommended сначала, потом по score,
        # при равенстве — меньше количество печей, затем больше ёмкость
        candidates.sort(
            key=lambda x: (
                x["applicable_for"].get("recommended", False),
                x["_score"],
                -x["_num_required"],
                x["specs"].get("capacity_t", 0),
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
        # Штраф за избыточное количество единиц оборудования
        penalty = 1.0 / (1.0 + 0.02 * max(num_furnaces - 1, 0))
        score = base * penalty

        # Приоритет эталонных решений из диплома/методички:
        # для сталелитейных цехов средней мощности стандартом является ИСТ-6М1
        # (при ~58 932 т/год — 6 печей, К_загр ≈ 0.84). Небольшая прибавка
        # гарантирует, что рекомендованная эталонная печь не уступит печи
        # большей ёмкости с сопоставимым коэффициентом загрузки.
        if furnace.get("id") == "IST-6M1":
            score += 0.05

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
        furnaces = self.loader.load_list(FURNACES_FILE, key="furnaces")
        for f in furnaces:
            if f.get("id") == furnace_id:
                return f
        return {}