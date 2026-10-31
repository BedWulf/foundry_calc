"""Verified manufacturer reference checks; never extrapolate operating data."""
import json
from pathlib import Path
from config import DATA_DIR


def matching_reference_units(material, feedstock, temperature_c, path=None):
    source_path = Path(path) if path else DATA_DIR / "verified_references" / "indotherm_casting_units.json"
    catalogue = json.loads(source_path.read_text(encoding="utf-8"))
    conditions = catalogue["conditions"]
    if (material != "steel" or feedstock != conditions["material"] or
            temperature_c != conditions["temperature_c"]):
        return []
    if catalogue.get("usage_policy") != "reference_only_no_automatic_selection":
        raise ValueError("Неподтверждённый режим использования справочника")
    result = []
    for item in catalogue["entries"]:
        if item.get("verification_status") != "manufacturer_catalog_verified":
            continue
        result.append({"id": item["id"], "name": item["name"],
                       "capacity_t": item["capacity_kg"] / 1000,
                       "published_productivity_t_h": item["published_melting_rate_kg_h"] / 1000,
                       "source_url": catalogue["source"]["url"],
                       "reference_only": True,
                       "eligible_for_final_design": False})
    return result


def manufacturer_ferrous_furnace_references(
    material: str, temperature_c: float, *,
    feedstock: str | None = None,
    data_dir: Path | None = None,
) -> list[dict]:
    """Reference-only candidate list with STRICT published conditions.

    This is the source-backed alternative to the legacy operational
    selector. No plant-approved final count, inferred load factor, furnace
    capacity midpoint, or undocumented steel-to-iron conversion is returned.

    Indotherm rates require steel SCRAP and 1675 C. IMF rates are published
    for steel at 1600 C and cast iron at 1450 C; feedstock is not specified
    in their brochure and therefore suitability remains unconfirmed.
    """
    from core.ferrous_furnace_catalog import nominal_reference_rates
    root = Path(data_dir) if data_dir is not None else DATA_DIR
    if material not in ("steel", "cast_iron"):
        return []
    result = list(nominal_reference_rates(material, temperature_c, root))
    if material == "steel" and feedstock == "steel scrap" and temperature_c == 1675:
        indotherm_path = root / "verified_references" / "indotherm_casting_units.json"
        steel_records = matching_reference_units(
            material, feedstock, temperature_c, path=indotherm_path
        )
        for record in steel_records:
            result.append({
                "model": record["name"],
                "material": "steel",
                "temperature_c": 1675,
                "feedstock": "steel scrap",
                "capacity_range_kg": (
                    record["capacity_t"] * 1000,
                    record["capacity_t"] * 1000,
                ),
                "nominal_melting_rate_kg_h": record["published_productivity_t_h"] * 1000,
                "source_url": record["source_url"],
                "source_row": record["id"],
                "source_page": "Casting Units, rows 01/02/05/09",
                "reference_only": True,
                "eligible_for_final_design": False,
            })
    return result
