"""Regressions for the frozen Windows startup crash reported 2026-10-30.

PyInstaller does not copy Python module source into _internal by default.
In particular there must be no runtime spec_from_file_location loader
for the historical root core/melting.py.
"""
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_melting_balance_has_normal_package_import_and_no_runtime_file_loader():
    import core.melting.charge as charge
    import core.melting.metal_balance as balance
    from core.melting import calc_metal_charge, MeltingCalculation

    assert charge.calc_metal_charge is balance.calc_metal_charge
    assert calc_metal_charge is balance.calc_metal_charge
    assert MeltingCalculation is balance.MeltingCalculation
    assert not hasattr(charge, "_load_legacy_module")
    assert not hasattr(charge, "LEGACY_MODULE_PATH")
    assert calc_metal_charge(37000, 7.2, 44.1, 5.0) > 58000


def test_actual_headless_gui_smoke_checks_melting_import(tmp_path, monkeypatch):
    # This is the same check that is triggered inside the frozen Windows EXE,
    # not the old shallow "do resource files exist?" check.
    from main import _smoke_test_frozen

    report = tmp_path / "startup_failure.txt"
    monkeypatch.setenv("FOUNDRY_SMOKE_REPORT", str(report))
    assert _smoke_test_frozen() == 0, (
        report.read_text(encoding="utf-8") if report.exists() else "")
    assert not report.exists()
