"""Manufacturer shortlist: only exact operating conditions, no fabricated rates."""
from core.verified_equipment_selection import manufacturer_ferrous_furnace_references


def test_published_imf_shortlist_requires_exact_metal_and_temperature():
    for mat, temp, exemplar in [
        ("steel", 1600, ("IMF 600 kW", 1000)),
        ("cast_iron", 1450, ("IMF 600 kW", 1100)),
    ]:
        rows = manufacturer_ferrous_furnace_references(mat, temp)
        assert len(rows) == 18
        found = next(x for x in rows if x["model"] == exemplar[0])
        assert found["nominal_melting_rate_kg_h"] == exemplar[1]
        assert found["source_page"] == 2
        assert all(r["reference_only"] is True and
                   r["eligible_for_final_design"] is False for r in rows)
        assert not any("num_furnaces" in r or "capacity_t" in r for r in rows)


def test_published_indotherm_requires_steel_scrap_and_1675_exact():
    assert manufacturer_ferrous_furnace_references("steel", 1675) == []
    assert manufacturer_ferrous_furnace_references(
        "steel", 1675, feedstock="pig iron"
    ) == []
    candidates = manufacturer_ferrous_furnace_references(
        "steel", 1675, feedstock="steel scrap"
    )
    assert len(candidates) == 9
    example = next(r for r in candidates if "1000 kg" in r["model"])
    assert example["nominal_melting_rate_kg_h"] == 875
    assert example["capacity_range_kg"] == (1000, 1000)
    assert example["reference_only"] is True
    assert example["eligible_for_final_design"] is False


def test_no_unsupported_cast_iron_steel_transfer_or_temperature_extrapolation():
    for material, temperature in [
        ("steel", 1601), ("cast_iron", 1449),
        ("cast_iron", 1675), ("aluminum", 720),
    ]:
        assert manufacturer_ferrous_furnace_references(
            material, temperature, feedstock="steel scrap"
        ) == []
