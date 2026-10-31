"""Source-backed steel/cast-iron furnace catalogue — nominal rates, not design approval.

INDUCTION s.r.l. brochure, PDF page 2: per-model melt-rate columns for
steel at 1600 C and cast iron at 1450 C. Capacity is a range. We NEVER
deduce operating throughput, charge count, or power from these data.
"""
from __future__ import annotations
import json
import math
from pathlib import Path
from config import DATA_DIR

SOURCE_URL = "https://induction.it/wp-content/uploads/brochure8_ted_ing_15.pdf"
ALLOWED_TEMPERATURES = {"steel": 1600, "cast_iron": 1450}


def load_imf_catalog(data_dir: Path | None = None) -> dict:
    root = Path(data_dir) if data_dir is not None else DATA_DIR
    path = root / "verified_references" / "induction_imf_ferrous_furnaces.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if (data.get("usage_policy") != "reference_only_no_automatic_selection"
            or data.get("source", {}).get("url") != SOURCE_URL
            or data.get("source", {}).get("page_pdf_1_based") != 2
            or not isinstance(data.get("entries"), list)):
        raise ValueError("Недостоверные метаданные производителя IMF")
    ids = set()
    for item in data["entries"]:
        model = item.get("model")
        if (item.get("id") in ids or not isinstance(model, str)
                or not model.startswith("IMF ")):
            raise ValueError("Повтор/неизвестная модель IMF")
        ids.add(item["id"])
        if item.get("verification_status") != "manufacturer_catalog_verified":
            raise ValueError(f"{model}: не подтверждено происхождение")
        if item.get("operation_validation_status") != "reference_only":
            raise ValueError(f"{model}: нельзя объявлять паспортный режим рабочим")
        source = item.get("source_reference", {})
        if (source.get("url") != SOURCE_URL or
                source.get("page_pdf_1_based") != 2 or
                source.get("table_row") != model):
            raise ValueError(f"{model}: не указана строка первоисточника")
        for field in ("power_kw", "capacity_min_kg", "capacity_max_kg"):
            val = item.get(field)
            if type(val) not in (int, float) or not math.isfinite(val) or val <= 0:
                raise ValueError(f"{model}: некорректный {field}")
        if item["capacity_min_kg"] > item["capacity_max_kg"]:
            raise ValueError(f"{model}: перепутаны границы ёмкости")
        rates = item.get("published_rates")
        if not isinstance(rates, list) or len(rates) != 2:
            raise ValueError(f"{model}: требуются два опубликованных режима")
        found = set()
        for rate in rates:
            material = rate.get("material")
            if (material not in ALLOWED_TEMPERATURES or material in found
                    or rate.get("temperature_c") != ALLOWED_TEMPERATURES.get(material)):
                raise ValueError(f"{model}: режим перепутан между сталями и чугуном")
            found.add(material)
            value = rate.get("rate_kg_h")
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{model}: неверная опубликованная производительность")
        if found != set(ALLOWED_TEMPERATURES):
            raise ValueError(f"{model}: неполные материалы")
    return data


def nominal_reference_rates(material: str, temperature_c: float,
                            data_dir: Path | None = None) -> list[dict]:
    """Show only EXACT documented melt conditions; no interpolation/extrapolation."""
    if material not in ALLOWED_TEMPERATURES:
        return []
    if type(temperature_c) not in (int, float) or not math.isfinite(temperature_c):
        raise ValueError("Неверная температура, °C")
    if temperature_c != ALLOWED_TEMPERATURES[material]:
        return []
    result = []
    for item in load_imf_catalog(data_dir)["entries"]:
        rate = next(r for r in item["published_rates"] if r["material"] == material)
        result.append({
            "model": item["model"], "power_kw": item["power_kw"],
            "capacity_range_kg": (item["capacity_min_kg"], item["capacity_max_kg"]),
            "material": material, "temperature_c": rate["temperature_c"],
            "nominal_melting_rate_kg_h": rate["rate_kg_h"],
            "source_url": SOURCE_URL, "source_page": 2,
            "source_row": item["source_reference"]["table_row"],
            "reference_only": True, "eligible_for_final_design": False,
        })
    return result


def imf_reference_display_rows(data_dir: Path | None = None) -> list[dict[str, str]]:
    rows = []
    for item in load_imf_catalog(data_dir)["entries"]:
        rates = {r["material"]: r for r in item["published_rates"]}
        rows.append({
            "name": f"INDUCTION s.r.l. {item['model']}",
            "specs": (f"Мощность {item['power_kw']:g} кВт; ёмкость "
                      f"{item['capacity_min_kg']:g}–{item['capacity_max_kg']:g} кг; "
                      f"сталь 1600 °C — {rates['steel']['rate_kg_h']:g} кг/ч; "
                      f"чугун 1450 °C — {rates['cast_iron']['rate_kg_h']:g} кг/ч"),
            "conditions": ("Опубликованы два номинальных режима. Ёмкость дана диапазоном; "
                           "не подтверждены режим цеха, доступный фонд, выход и простои."),
            "source": f"Каталог INDUCTION s.r.l., стр. 2, таблица, строка {item['model']}",
            "url": SOURCE_URL,
            "status": "Справочные данные изготовителя; автоматический окончательный подбор запрещён",
        })
    return rows
