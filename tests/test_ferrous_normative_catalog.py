"""GOST 977/1412/7293/1215: exact bounded ferrous norms, never process defaults."""
import copy
import json
from pathlib import Path

from core.ferrous_normative_catalog import (
    load_ferrous_catalog, validate_ferrous_catalog,
    get_ferrous_grade_properties, property_description,
)

DATA = Path(__file__).resolve().parents[1] / "data"


def test_42_ferrous_grades_and_114_documented_properties():
    data = load_ferrous_catalog(DATA)
    assert len(data["records"]) == 42
    assert sum(len(r["properties"]) for r in data["records"]) == 114
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
    # Newly verified alloyed steel now exists; unverified variants remain absent.
    assert get_ferrous_grade_properties("steel", "20ГЛ", DATA) is not None
    assert get_ferrous_grade_properties("steel", "12Х7Г3СЛ", DATA) is None


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
    for modification in ("nan", "unit", "source", "color", "auto", "wrong_gost_url", "dup"):
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
        elif modification == "wrong_gost_url":
            broken["sources"]["GOST_977_88"]["source_url"] = (
                broken["sources"]["GOST_1412_85"]["source_url"])
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
            assert value["source"]["location"]
            if "строка " in value["source"]["location"]:
                assert r["name"] in value["source"]["location"]
            else:
                assert value["source"]["location"] == source["location"]
            assert value["source"]["standard_id"] == r["standard_id"]
            assert property_description(field, value)
    assert get_ferrous_grade_properties("aluminum", "АК12", DATA) is None


def test_four_alloyed_steels_have_exact_gost_table_one_ranges_and_maxima():
    # Values transcribed from section 1.3/table 1, NOT derived from steel grade names.
    expected = {
        "20ГЛ": ((.15,.25),(1.20,1.60),(.20,.40),.040,.040),
        "35ГЛ": ((.30,.40),(1.20,1.60),(.20,.40),.040,.040),
        "20ГСЛ": ((.16,.22),(1.00,1.30),(.60,.80),.030,.030),
        "30ГСЛ": ((.25,.35),(1.10,1.40),(.60,.80),.040,.040),
    }
    for grade, (c,mn,si,p,s) in expected.items():
        row = get_ferrous_grade_properties("steel", grade, DATA)
        assert row is not None
        assert row["standard_id"] == "GOST_977_88"
        for field, expected_pair in [
            ("carbon_mass_pct", c), ("manganese_mass_pct", mn),
            ("silicon_mass_pct", si),
        ]:
            item = row["properties"][field]
            assert item["kind"] == "normative_range"
            assert (item["min"], item["max"]) == expected_pair
            assert item["unit"] == "mass_%"
            assert grade in item["source"]["location"]
        for field, maximum in [
            ("phosphorus_mass_pct", p), ("sulfur_mass_pct", s),
        ]:
            item = row["properties"][field]
            assert item["kind"] == "normative_maximum"
            assert item["value"] == maximum
            assert item["unit"] == "mass_%"
            assert grade in item["source"]["location"]
            assert property_description(field, item).startswith(
                ("P:" if field == "phosphorus_mass_pct" else "S:")
                + " не более "
            )


def test_wrong_alloyed_steel_source_and_impurity_kind_fail_closed():
    d = load_ferrous_catalog(DATA)
    index = json.loads(
        (DATA / "verified_references" / "alloy_standards.json")
        .read_text(encoding="utf-8")
    )
    for defect in ("other_grade", "impurity_as_range", "negative_limit", "bad_number"):
        broken = copy.deepcopy(d)
        row = next(r for r in broken["records"] if r["name"] == "20ГСЛ")
        p = row["properties"]["phosphorus_mass_pct"]
        if defect == "other_grade":
            p["source"]["location"] = "п. 1.3, таблица 1, строка 35ГЛ"
        elif defect == "impurity_as_range":
            p.update(kind="normative_range", min=0.0, max=0.03)
        elif defect == "negative_limit":
            p["value"] = -0.03
        else:
            p["value"] = "0.03"
        assert validate_ferrous_catalog(broken, index), defect


def test_all_eleven_malleable_iron_brinell_ranges_exact():
    # GOST 1215-79 section 3.2, table 1; no hardness inferred from strength.
    expected = {
        "КЧ30-6": (100,163), "КЧ33-8": (100,163),
        "КЧ35-10": (100,163), "КЧ37-12": (110,163),
        "КЧ45-7": (150,207), "КЧ50-5": (170,230),
        "КЧ55-4": (192,241), "КЧ60-3": (200,269),
        "КЧ65-3": (212,269), "КЧ70-2": (241,285),
        "КЧ80-1,5": (270,320),
    }
    for grade, (low, high) in expected.items():
        record = get_ferrous_grade_properties("malleable_iron", grade, DATA)
        hb = record["properties"]["brinell_hardness_hb"]
        assert hb["kind"] == "normative_range"
        assert hb["unit"] == "HB"
        assert (hb["min"], hb["max"]) == (low, high)
        assert grade in hb["source"]["location"]
        assert property_description("brinell_hardness_hb", hb).endswith("HB")


def test_nonexistent_malleable_iron_hardness_is_not_assumed():
    assert get_ferrous_grade_properties("malleable_iron", "КЧ99-99", DATA) is None


def test_gost_chromium_bounds_for_32x06l_and_40xl():
    expected = {
        "32Х06Л": ((.25, .35), (.40, .90), (.20, .40), .050, .050, (.50, .80)),
        "40ХЛ": ((.35, .45), (.40, .90), (.20, .40), .040, .040, (.80, 1.10)),
    }
    for grade, (carbon, manganese, silicon, p, s, chromium) in expected.items():
        record = get_ferrous_grade_properties("steel", grade, DATA)
        assert record is not None and record["standard_id"] == "GOST_977_88"
        for key, bounds in (
            ("carbon_mass_pct", carbon), ("manganese_mass_pct", manganese),
            ("silicon_mass_pct", silicon), ("chromium_mass_pct", chromium),
        ):
            v = record["properties"][key]
            assert (v["min"], v["max"]) == bounds
            assert v["kind"] == "normative_range"
            assert grade in v["source"]["location"]
        for key, maximum in (("phosphorus_mass_pct", p), ("sulfur_mass_pct", s)):
            v = record["properties"][key]
            assert v["kind"] == "normative_maximum" and v["value"] == maximum
