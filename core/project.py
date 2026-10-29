"""Модель проекта литейного цеха."""
import hashlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import date
from .casting_item import CastingItem


@dataclass
class Project:
    """Корневая модель проекта — все данные цеха."""

    # --- Идентификация ---
    name: str = "Проект литейного цеха"
    created_at: date = field(default_factory=date.today)
    customer: str = ""

    # --- Производственная программа ---
    annual_output_t: float = 37000.0
    alloy: str = "Сталь 20Л ГОСТ 977-88"
    alloy_density_kg_m3: float = 7800.0
    selected_alloy_id: str = "steel_20L"  # ← НОВОЕ

    # --- Режим работы ---
    shifts_per_day: int = 2
    shift_duration_h: float = 8.0
    working_days_per_year: int = 249

    # План общих формовочных линий: партии, переналадки и резерв фонда.
    molding_batches_per_year: int = 1
    molding_setup_h: float = 0.0  # не задано; оптимистичная оценка
    molding_max_load_factor: float = 0.85
    # "auto" — число и модели выбираются автоматически;
    # "manual" — используется ровно заданный парк, даже если мощности не хватит.
    molding_park_mode: str = "auto"
    molding_line_counts: Dict[str, int] = field(default_factory=dict)

    # --- Брак и потери ---
    brak_pct: float = 5.0
    litniki_pribyli_pct: float = 28.9
    ugar_pct: float = 5.0

    # --- Номенклатура отливок ---
    castings: List[CastingItem] = field(default_factory=list)

    # --- Производные ---
    F_calendar_h: float = 8760.0
    F_nominal_h: float = 5976.0
    F_equipment_h: float = 3890.0
    F_workers_h: float = 3975.0
    metal_charge_t: float = 0.0
    liquid_metal_t: float = 0.0

    # ---------- методы ----------
    @property
    def project_id(self) -> str:
        """Стабильный идентификатор проекта для user_data/choices.json.

        Вычисляется из названия и даты создания, поэтому выбор оборудования
        корректно восстанавливается между запусками приложения.
        """
        raw = f"{self.name}|{self.created_at.isoformat()}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]

    def add_casting(self, item: CastingItem) -> None:
        self.castings.append(item)

    def clear_castings(self) -> None:
        self.castings.clear()

    def total_castings_count(self) -> int:
        return len(self.castings)

    def total_castings_mass_t(self) -> float:
        return sum(c.annual_mass_t for c in self.castings)

    def summary(self) -> dict:
        return {
            "annual_output_t": self.annual_output_t,
            "castings_count": self.total_castings_count(),
            "castings_mass_t": round(self.total_castings_mass_t(), 2),
            "metal_charge_t": round(self.metal_charge_t, 2),
            "F_calendar_h": self.F_calendar_h,
            "F_nominal_h": self.F_nominal_h,
            "F_equipment_h": self.F_equipment_h,
            "F_workers_h": self.F_workers_h,
            "selected_alloy_id": self.selected_alloy_id,
        }