"""Модель одной отливки (позиции номенклатуры)."""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CastingItem:
    """Одна позиция номенклатуры отливок."""

    # --- Идентификация ---
    index: int = 1                          # порядковый номер
    name: str = ""                          # наименование (Блок, Диск, ...)
    drawing: str = ""                       # обозначение чертежа

    # --- Геометрия ---
    mass_with_LPS_kg: float = 0.0           # масса с ЛПС, кг (заливочная масса)
    mass_casting_kg: float = 0.0            # масса чистой отливки, кг
    dimensions_mm: str = ""                 # габариты (Ø180, 156x... и т.п.)
    wall_thickness_mm: float = 0.0          # характерная толщина стенки
    length_mm: float = 0.0
    width_mm: float = 0.0
    height_mm: float = 0.0

    # --- Программа выпуска ---
    annual_qty_pcs: int = 0                 # годовой годный выпуск, шт
    brak_pct: float = 5.0                   # % брака на данную отливку
    annual_qty_with_brak: int = 0           # с учётом брака

    # --- Форма ---
    flask_size_mm: str = "900x600x200/200"  # размер опок
    molds_per_year: int = 0                 # годовое кол-во форм
    pouring_mass_kg: float = 0.0            # масса заливаемого металла в форму
    annual_metal_t: float = 0.0             # масса металла в год по позиции, т
    mix_volume_m3: float = 0.0              # объём формовочной+стержневой смеси

    # --- Стержни ---
    cores_count: int = 0                    # кол-во стержней в форме
    core_volume_m3: float = 0.0             # объём стержневой смеси на форму
    core_mass_kg: float = 0.0

    # --- Тип оснастки ---
    molding_machine: str = "ИЛ-225"
    core_machine: str = ""

    # ---------- методы ----------
    @property
    def total_metal_mass_t(self) -> float:
        """Полная масса металла по позиции за год (т)."""
        return self.annual_metal_t

    @property
    def annual_mass_t(self) -> float:
        """Масса металла по заливке за год для импортированной позиции.

        Не путать с годной массой отливок: для последней необходимы
        масса без ЛПС и процент фактического брака.
        """
        return self.annual_metal_t

    def validate(self) -> bool:
        """Базовая валидация полей."""
        return (
            self.name.strip() != ""
            and self.annual_qty_pcs > 0
            and self.mass_with_LPS_kg > 0
        )