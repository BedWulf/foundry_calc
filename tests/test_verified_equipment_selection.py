from core.verified_equipment_selection import matching_reference_units


def test_exact_published_conditions_only():
    rows = matching_reference_units("steel", "steel scrap", 1675)
    assert len(rows) == 9
    assert all(row["reference_only"] for row in rows)
    assert all(not row["eligible_for_final_design"] for row in rows)


def test_other_alloy_or_temperature_never_reuses_steel_scrap_rate():
    assert matching_reference_units("cast_iron", "steel scrap", 1675) == []
    assert matching_reference_units("steel", "steel scrap", 1600) == []
    assert matching_reference_units("steel", "steel scrap", 1675 + 1) == []
    assert matching_reference_units("steel", "different feedstock", 1675) == []
