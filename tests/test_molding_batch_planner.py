"""Independent capacity and conservation checks for shared molding lines."""
from types import SimpleNamespace

import pytest

from core.molding_batch_planner import (
    MoldingJob, build_jobs_from_castings, plan_molding_batches,
)


def machine(name, flask="900x600", speed=100):
    return {
        "id": name, "name": name,
        "specs": {"flask_size_mm": flask, "flask_heights_mm": [200],
                  "nominal_productivity_molds_h": speed, "max_mold_metal_kg": 100,
                  "installed_power_kw": 50},
        "applicable_for": {"materials": ["steel"], "casting_mass_range_kg": [0, 100]},
    }


def job(key, molds, flask="900x600x200", batches=1, setup=0):
    return MoldingJob(key, key, molds, flask, "steel", 5, 10, batches, setup)


def test_multiple_castings_share_one_line():
    jobs = [job("A", 70_000), job("B", 80_000)]
    p = plan_molding_batches(jobs, [machine("L")], 2_000, max_load_factor=.85)
    assert p.feasible and len(p.lines) == 1
    assert {c.job_key for c in p.lines[0].campaigns} == {"A", "B"}
    assert p.assigned_molds == 150_000


def test_large_batch_splits_but_preserves_all_molds():
    jobs = [job("A", 500_000)]
    p = plan_molding_batches(jobs, [machine("L")], 2000, max_load_factor=.85)
    assert p.feasible and len(p.lines) == 3
    assert sum(c.molds for ln in p.lines for c in ln.campaigns) == 500_000
    assert all(ln.used_hours <= ln.allowed_hours + 1e-6 for ln in p.lines)


def test_different_flasks_use_different_lines():
    jobs = [job("A", 80000), job("B", 80000, "1100x750x200")]
    p = plan_molding_batches(jobs, [machine("L"), machine("B", "1100x750")], 2000)
    assert p.feasible and {ln.equipment_id for ln in p.lines} == {"L", "B"}


def test_setup_time_increases_required_capacity():
    jobs = [job("A", 90000, setup=100), job("B", 90000, setup=100)]
    p = plan_molding_batches(jobs, [machine("L")], 1900, max_load_factor=1)
    assert p.feasible and len(p.lines) == 2


def test_unmatched_job_not_silently_discarded():
    jobs = [job("A", 20000, flask="1400x900x200")]
    p = plan_molding_batches(jobs, [machine("L")], 2000)
    assert not p.feasible and p.assigned_molds == 0 and p.unassigned == ["A"]


def test_scrap_and_castings_per_mold_conversion():
    c = SimpleNamespace(name="Блок", annual_qty_pcs=100, annual_qty_with_brak=0,
                        molds_per_year=0, castings_per_mold=4, brak_pct=20,
                        flask_size_mm="900x600x200", mass_with_LPS_kg=2,
                        pouring_mass_kg=9)
    assert build_jobs_from_castings([c], "steel")[0].annual_molds == 32


def test_invalid_fund_rejected():
    with pytest.raises(ValueError):
        plan_molding_batches([job("A", 10)], [machine("L")], 0)
