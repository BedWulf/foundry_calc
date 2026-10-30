"""Independent audits of casting quantities and poured-metal conservation.

Checks never rewrite source quantities or invent a technological coefficient.
A known discrepancy is not resolved by matching a diploma example.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

from .casting_item import CastingItem


@dataclass(frozen=True)
class CastingIssue:
    row: int
    name: str
    severity: str  # "inconsistent" or "unverified"
    code: str
    message: str

    def describe(self) -> str:
        return f"Отливка №{self.row} ({self.name}): {self.message}"


def audit_castings(castings: Iterable[CastingItem]) -> list[CastingIssue]:
    """Check independent mold counts and mass balances per casting row.

    annual_qty_with_brak: pieces/year of this specific casting (when known)
    castings_per_mold: pieces/mold of the specific casting
    molds_per_year: molds/year
    pouring_mass_kg: ALL poured metal per mold, not per casting
    annual_metal_t: tonnes of poured metal per year

    Unknown source fields are reported as unverified, never assumed zero.
    Disagreements use tolerances only for source rounding, not to conceal
    large inconsistencies. We do NOT assert that separate mold lots are
    shared between different casting rows.
    """
    issues: list[CastingIssue] = []
    for row, c in enumerate(castings, 1):
        name = str(c.name or "без наименования")

        def issue(severity: str, code: str, message: str) -> None:
            issues.append(CastingIssue(row, name, severity, code, message))

        molds = c.molds_per_year
        qty = c.annual_qty_with_brak
        per = c.castings_per_mold
        pour = c.pouring_mass_kg
        mass = c.mass_with_LPS_kg
        annual = c.annual_metal_t
        if any(type(v) is not int or v < 0
               for v in (molds, qty, per)):
            issue("inconsistent", "counts", "отрицательное или нецелое количество форм/отливок")
            continue
        if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0
               for v in (pour, mass, annual)):
            issue("inconsistent", "masses", "массы должны быть конечными неотрицательными числами")
            continue

        if molds == 0:
            issue("unverified", "no_molds", "не задано годовое число форм")
        if qty == 0:
            issue("unverified", "no_pieces", "не задано количество отливок с учётом брака")
        if per == 0:
            issue("unverified", "no_multiplicity", "не указано число отливок в форме")
        if qty > 0 and per > 0 and molds > 0:
            expected = math.ceil(qty / per)
            if molds != expected:
                issue(
                    "inconsistent", "mold_count",
                    f"указано {molds} форм/год, а ceil({qty}/{per}) = {expected}; "
                    "проверьте количество отливок и распределение по формам")

        if pour == 0:
            issue("unverified", "no_pour_mass", "неизвестна масса заливки одной формы")
        elif c.pouring_mass_estimated:
            issue("unverified", "estimated_pour_mass",
                  "масса заливки рассчитана как масса с ЛПС × число отливок; "
                  "не подтверждена по технологической карте")
        if mass == 0:
            issue("unverified", "no_casting_mass", "неизвестна масса отливки с ЛПС")
        if pour > 0 and mass > 0 and per > 0:
            # Shared gating may appear in several per-casting LPS masses:
            # this is a WARNING about definitions, not proof of a physical
            # impossibility or a reason to overwrite the source values.
            minimum = mass * per
            if pour < minimum - max(0.02, minimum * 0.001):
                issue("inconsistent", "mass_per_mold",
                      f"масса заливки {pour:g} кг/форму меньше C×G={minimum:g} кг. "
                      "Уточните, как распределена масса общей ЛПС")
        if annual == 0:
            issue("unverified", "no_annual_metal",
                  "годовая масса заливаемого металла не задана")
        elif pour > 0 and molds > 0:
            expected_t = molds * pour / 1000.0
            if abs(annual - expected_t) > max(0.002, expected_t * 0.001):
                issue("inconsistent", "annual_mass",
                      f"металл {annual:g} т/год не согласуется с "
                      f"{molds} форм × {pour:g} кг/форму = {expected_t:g} т/год")
    return issues
