"""Independent algebra and input-domain checks of the melting mass balance.

These checks cover the code's declared equation, not equipment passport
authenticity or an independent review of the source diploma PDFs.
"""
import json
import pytest

from core.melting import calc_metal_charge, REFERENCE_YIELD
from core.project import Project
from core.project_io import ProjectFileError, read_project, write_project


def test_default_parameters_do_not_claim_diploma_one_mass():
    # 37 000 t good casting + 28.9% runners + 5% rejects, with 5% burn-off.
    expected = 37_000 * (1 + .289 + .05) / .95
    assert expected == pytest.approx(52_150.52631578947)
    assert calc_metal_charge(37_000) == pytest.approx(expected)
    assert abs(expected - 58_932) > 6_000


def test_reference_mass_balance_exposes_both_numerator_and_burnoff():
    good, runners, rejected, burnoff = 37_000, 16_320, 2_666, .05
    demand = (good + runners + rejected) / (1 - burnoff)
    assert calc_metal_charge(
        good, brak_pct=rejected / good * 100,
        litniki_pribyli_pct=runners / good * 100,
        ugar_pct=burnoff * 100,
    ) == pytest.approx(demand)
    assert demand * (1 - burnoff) == pytest.approx(good + runners + rejected)


@pytest.mark.parametrize("kwargs", [
    {"annual_output_t": -1},
    {"annual_output_t": float("nan")},
    {"annual_output_t": float("inf")},
    {"annual_output_t": True},
    {"annual_output_t": "1000"},
    {"brak_pct": -0.1},
    {"brak_pct": float("nan")},
    {"brak_pct": float("inf")},
    {"litniki_pribyli_pct": -1},
    {"litniki_pribyli_pct": float("nan")},
    {"ugar_pct": -1},
    {"ugar_pct": 100},
    {"ugar_pct": 150},
    {"ugar_pct": float("nan")},
    {"ugar_pct": True},
])
def test_invalid_metal_balance_inputs_raise(kwargs):
    args = {
        "annual_output_t": 1000, "brak_pct": 5.0,
        "litniki_pribyli_pct": 28.9, "ugar_pct": 5.0,
    }
    args.update(kwargs)
    with pytest.raises(ValueError):
        calc_metal_charge(**args)


def test_zero_output_is_zero_only_for_valid_loss_parameters():
    assert calc_metal_charge(0, brak_pct=5, ugar_pct=5) == 0
    with pytest.raises(ValueError):
        calc_metal_charge(0, ugar_pct=100)


@pytest.mark.parametrize("field,value", [
    ("ugar_pct", 100),
    ("ugar_pct", -1),
    ("brak_pct", -5),
    ("litniki_pribyli_pct", -12),
])
def test_invalid_losses_do_not_overwrite_existing_project(tmp_path, field, value):
    source = tmp_path / "casting.fpro.json"
    project = Project(name="Safe")
    write_project(source, project)
    before = source.read_bytes()
    setattr(project, field, value)
    with pytest.raises(ProjectFileError):
        write_project(source, project)
    assert source.read_bytes() == before


@pytest.mark.parametrize("field,value", [
    ("ugar_pct", 100), ("ugar_pct", -1),
    ("brak_pct", -0.5), ("litniki_pribyli_pct", -2),
])
def test_invalid_percentages_in_json_rejected_before_gui(tmp_path, field, value):
    path = tmp_path / "untrusted.fpro.json"
    write_project(path, Project())
    data = json.loads(path.read_text(encoding="utf-8"))
    data["project"][field] = value
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ProjectFileError):
        read_project(path)


def test_reference_yield_matches_stated_mass_figures():
    # Reference yield is an algebraic ratio; prior 0.611 was inconsistent.
    assert REFERENCE_YIELD == pytest.approx(37_000 / 58_932)
    assert REFERENCE_YIELD == pytest.approx(.6278422588746352)
