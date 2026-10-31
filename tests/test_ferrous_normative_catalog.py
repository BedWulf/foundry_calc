"""GOST 977/1412/7293/1215: exact bounded ferrous norms, never process defaults."""
import copy
import json
from pathlib import Path

from core.ferrous_normative_catalog import (
    load_ferrous_catalog, validate_ferrous_catalog,
    get_ferrous_grade_properties, property_description,
)

DATA = Path(__file__).resolve().parents[1] / "data"


def test_36_ferrous_grades_and_71_documented_properties():
    data = load_ferrous_catalog(DATA)
    assert len(data["records"]) == 36
    assert sum(len(r["properties"]) for r in data["records"]) == 71
    assert {r["category"] for r in data["records"]} == {
        "steel", "cast_iron", "ductile_iron", "malleable_iron",
    }
    assert all(r["eligible_for_process_calculations"] is False
               for r in data["records"])
    assert all("density_kg_m3" not in r["properties"] and
               "pouring_temp_C" not in r["properties"] for r in data["records"])


def test_unalloyed_steel_ranges_follow_table_one_not_middle_values():
    for name, low, high in [
        ("15Л", .12, .20), ("20Л", .17, .25),
        ("25Л", .22, .30), ("30Л", .27, .35),
        ("35Л", .32, .40), ("40Л", .37, .45),
        ("45Л", .42, .50), ("50Л", .47, .55),
    ]:
        record = get_ferrous_grade_properties("steel", name, DATA)
        assert record["properties"]["carbon_mass_pct"]["min"] == low
        assert record["properties"]["carbon_mass_pct"]["max"] == high
        assert record["properties"]["manganese_mass_pct"]["min"] == .45
        assert record["properties"]["manganese_mass_pct"]["max"] == .90
        assert record["properties"]["silicon_mass_pct"]["min"] == .20
        assert record["properties"]["silicon_mass_pct"]["max"] == .52
    assert get_ferrous_grade_properties("steel", "20ГЛ", DATA) is None


def test_gray_ductile_and_malleable_mechanical_properties_are_minimums():
    for name, strength in {
        "СЧ10": 100, "СЧ15": 150, "СЧ18": 180, "СЧ20": 200,
        "СЧ21": 210, "СЧ24": 240, "СЧ25": 250, "СЧ30": 300, "СЧ35": 350,
    }.items():
        r = get_ferrous_grade_properties("cast_iron", name, DATA)
        assert r["properties"]["tensile_strength_min_mpa"]["value"] == strength
        assert "normative_minimum" == r["properties"]["tensile_strength_min_mpa"]["kind"]
    r = get_ferrous_grade_properties("cast_iron", "СЧ10", DATA)
    assert "по требованию потребителя" in r["scope"]
    for name, tensile, proof in [
        ("ВЧ35",350,220),("ВЧ40",400,250),("ВЧ45",450,310),
        ("ВЧ50",500,320),("ВЧ60",600,370),("ВЧ70",700,420),
        ("ВЧ80",800,480),("ВЧ100",1000,700),
    ]:
        r = get_ferrous_grade_properties("ductile_iron", name, DATA)
        assert r["properties"]["tensile_strength_min_mpa"]["value"] == tensile
        assert r["properties"]["proof_strength_min_mpa"]["value"] == proof
    for name, tensile, elongation in [
        ("КЧ30-6",294,6),("КЧ33-8",323,8),("КЧ35-10",333,10),
        ("КЧ37-12",362,12),("КЧ45-7",441,7),("КЧ50-5",490,5),
        ("КЧ55-4",539,4),("КЧ60-3",588,3),("КЧ65-3",637,3),
        ("КЧ70-2",686,2),("КЧ80-1,5",784,1.5),
    ]:
        r = get_ferrous_grade_properties("malleable_iron", name, DATA)
        assert r["properties"]["tensile_strength_min_mpa"]["value"] == tensile
        assert r["properties"]["elongation_min_pct"]["value"] == elongation


def test_reject_invalid_units_sources_nonfinite_ranges_or_color_entries():
    data = load_ferrous_catalog(DATA)
    index = json.loads(
        (DATA/"verified_references"/"alloy_standards.json").read_text(encoding="utf-8")
    )
    assert validate_ferrous_catalog(data, index) == []
    for modification in ("nan", "unit", "source", "color", "auto", "dup"):
        broken = copy.deepcopy(data)
        r = broken["records"][0]
        if modification == "nan":
            r["properties"]["carbon_mass_pct"]["min"] = float("nan")
        elif modification == "unit":
            r["properties"]["carbon_mass_pct"]["unit"] = "kg"
        elif modification == "source":
            r["properties"]["carbon_mass_pct"]["source"]["standard_id"] = "other"
        elif modification == "color":
            r["category"] = "aluminum"
        elif modification == "auto":
            r["eligible_for_process_calculations"] = True
        else:
            broken["records"].append(copy.deepcopy(r))
        assert validate_ferrous_catalog(broken, index), modification


def test_explicit_sources_and_no_aluminium_new_properties():
    data = load_ferrous_catalog(DATA)
    for r in data["records"]:
        source = data["sources"][r["standard_id"]]
        assert source["source_url"].startswith("https://protect.gost.ru/")
        assert source["text_url"].startswith("https://")
        for field, value in r["properties"].items():
            assert value["source"]["location"] == source["location"]
            assert value["source"]["standard_id"] == r["standard_id"]
            assert property_description(field, value)
    assert get_ferrous_grade_properties("aluminum", "АК12", DATA) is None
