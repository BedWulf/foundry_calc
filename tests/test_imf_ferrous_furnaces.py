"""Primary-source regression: INDUCTION s.r.l. brochure p.2, steel and iron.

Full manufacturer source:
https://induction.it/wp-content/uploads/brochure8_ted_ing_15.pdf
Values are nominal published rates, not measured actual foundry throughput.
"""
import copy
import json
from pathlib import Path
import pytest

from core.ferrous_furnace_catalog import (
    load_imf_catalog, nominal_reference_rates, imf_reference_display_rows,
)

ROOT = Path(__file__).resolve().parents[1] / "data"

# IMF kW: min charge, max charge, steel@1600 °C, cast iron@1450 °C
SOURCE_ROWS = {
    15: (15,20,20,25), 30: (30,40,40,45), 50: (50,70,70,75),
    100: (100,200,140,155), 200: (200,300,315,350),
    300: (300,500,480,520), 400: (500,750,650,700),
    600: (750,1000,1000,1100), 800: (1000,1500,1300,1530),
    1000: (1500,2000,1700,1950), 1200: (2000,2500,2040,2350),
    1500: (2500,3000,2500,2950), 1750: (3000,3500,2900,3450),
    2000: (3500,4000,3350,3950), 3000: (4000,5000,5050,5900),
    5000: (6000,8000,8450,9900), 6000: (8000,10000,10100,11800),
    8000: (12000,15000,13400,15700),
}


def test_exact_18_manufacturer_rows_and_both_materials():
    data = load_imf_catalog(ROOT)
    assert len(data["entries"]) == 18
    by_kw = {row["power_kw"]: row for row in data["entries"]}
    assert set(by_kw) == set(SOURCE_ROWS)
    for power, (lo, hi, steel, iron) in SOURCE_ROWS.items():
        record = by_kw[power]
        assert record["model"] == f"IMF {power} kW"
        assert (record["capacity_min_kg"], record["capacity_max_kg"]) == (lo, hi)
        assert {r["material"]: (r["temperature_c"], r["rate_kg_h"])
                for r in record["published_rates"]} == {
                    "steel": (1600, steel), "cast_iron": (1450, iron),
                }
        assert record["source_reference"]["page_pdf_1_based"] == 2
        assert record["source_reference"]["table_row"] == record["model"]
        assert record["operation_validation_status"] == "reference_only"


def test_only_exact_temperature_and_material_and_no_annualized_guesses():
    for material, temperature in (("steel",1600), ("cast_iron",1450)):
        matches = nominal_reference_rates(material,temperature,ROOT)
        assert len(matches) == 18
        assert all(x["reference_only"] is True and
                   x["eligible_for_final_design"] is False for x in matches)
        for x in matches:
            assert "furnace_count" not in x
            assert "annual_throughput_t" not in x
            assert "capacity_t" not in x  # manufacturer states a range
    assert nominal_reference_rates("steel",1450,ROOT) == []
    assert nominal_reference_rates("cast_iron",1600,ROOT) == []
    assert nominal_reference_rates("steel",1650,ROOT) == []
    assert nominal_reference_rates("aluminum",720,ROOT) == []
    with pytest.raises(ValueError):
        nominal_reference_rates("steel",float("nan"),ROOT)


def test_source_is_visible_with_unit_and_temperature():
    rows = imf_reference_display_rows(ROOT)
    assert len(rows) == 18
    record = next(x for x in rows if x["name"].endswith("IMF 600 kW"))
    assert "750–1000 кг" in record["specs"]
    assert "сталь 1600 °C — 1000 кг/ч" in record["specs"]
    assert "чугун 1450 °C — 1100 кг/ч" in record["specs"]
    assert "строка IMF 600 kW" in record["source"]
    assert record["url"].endswith("brochure8_ted_ing_15.pdf")


def test_manifest_corruption_wrong_model_material_or_temperature_is_rejected(tmp_path):
    original = load_imf_catalog(ROOT)
    for defect in ("duplicate", "wrong_temp", "wrong_row", "swapped_material", "nan", "approval"):
        data = copy.deepcopy(original)
        target = data["entries"][0]
        if defect == "duplicate":
            data["entries"].append(copy.deepcopy(target))
        elif defect == "wrong_temp":
            target["published_rates"][0]["temperature_c"] = 1599
        elif defect == "wrong_row":
            target["source_reference"]["table_row"] = "IMF 30 kW"
        elif defect == "swapped_material":
            target["published_rates"][1]["material"] = "steel"
        elif defect == "nan":
            target["published_rates"][0]["rate_kg_h"] = float("nan")
        else:
            target["operation_validation_status"] = "validated_for_plant"
        folder = tmp_path / "verified_references"
        folder.mkdir(exist_ok=True)
        (folder / "induction_imf_ferrous_furnaces.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
        with pytest.raises(ValueError):
            load_imf_catalog(tmp_path)
