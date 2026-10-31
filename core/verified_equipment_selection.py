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
