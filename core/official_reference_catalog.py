"""Read built-in manufacturer references without pretending they prove suitability.

All entries originate from versioned files shipped with the application.
User files are not needed. This module never extrapolates a dry core cycle,
assigns missing metal-mass limits, or invents a process coefficient.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from config import DATA_DIR


def _read(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, dict):
        raise ValueError(f"Некорректная структура справочника: {path.name}")
    if data.get("usage_policy", "").startswith("reference_only") is False:
        raise ValueError(f"Нет ограничений применения: {path.name}")
    return data


def _verified_number(item: dict, field: str, unit: str) -> str:
    value = item.get(field)
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"Некорректная характеристика {field}")
    return f"{value:g} {unit}"


def list_official_references(data_dir: Path | None = None) -> dict[str, list[dict[str, str]]]:
    """Four display categories; values are literal manufacturer/GOST evidence.

    The presence of a record here never makes it eligible for final design.
    """
    root = Path(data_dir) if data_dir is not None else DATA_DIR
    folder = root / "verified_references"
    furnace = _read(folder / "indotherm_casting_units.json")
    sinto = _read(folder / "sinto_foundry_equipment.json")
    grades = _read(folder / "alloy_standards.json")
    out: dict[str, list[dict[str, str]]] = {
        "Плавильные печи": [], "Формовочные линии": [],
        "Стержневые машины": [], "Марки материалов": [],
    }
    url = furnace["source"]["url"]
    for item in furnace["entries"]:
        if item.get("verification_status") != "manufacturer_catalog_verified":
            raise ValueError(f"{item.get('id')}: не подтверждён источник")
        out["Плавильные печи"].append({
            "name": item["name"],
            "specs": (f"Ёмкость {_verified_number(item, 'capacity_kg', 'кг')}; "
                      f"мощность {_verified_number(item, 'power_kw', 'кВт')}; "
                      f"плавка стали {_verified_number(item, 'published_melting_rate_kg_h', 'кг/ч')}; "
                      f"частота {_verified_number(item, 'frequency_hz', 'Гц')}"),
            "conditions": "Стальной лом, 1675 °C, опубликованное допущение 100% выхода",
            "source": "Indotherm — " + item["source_reference"]["location"],
            "url": url,
            "status": "Параметры из каталога; пригодность для проекта не проверена",
        })
    for item in sinto["molding_lines"]:
        if item.get("verification_status") != "manufacturer_catalog_verified":
            raise ValueError(f"{item.get('id')}: не подтверждён источник")
        spec = item["specs"]
        src = sinto["sources"][item["source_id"]]
        out["Формовочные линии"].append({
            "name": f"Sinto {item['model']}",
            "specs": (f"Форма {_verified_number(spec, 'mold_width_mm', 'мм')} × "
                      f"{_verified_number(spec, 'mold_length_mm', 'мм')}; "
                      f"высота {_verified_number(spec, 'mold_height_min_mm', 'мм')}–"
                      f"{_verified_number(spec, 'mold_height_max_mm', 'мм')}; "
                      f"опубликовано {_verified_number(spec, 'published_molding_rate_molds_h', 'форм/ч')}"),
            "conditions": "Air-flow + squeeze; металлоёмкость формы не опубликована",
            "source": src["document_title"] + ", " + item["source_reference"]["location"],
            "url": src["url"],
            "status": "Параметры из каталога; пригодность для проекта не проверена",
        })
    for item in sinto["core_machines"]:
        if item.get("verification_status") != "manufacturer_catalog_verified":
            raise ValueError(f"{item.get('id')}: не подтверждён источник")
        spec = item["specs"]
        dims = spec["max_core_box_dimensions_mm"]
        if len(dims) != 3 or not all(type(x) in (int,float) and x > 0 for x in dims):
            raise ValueError("Неверные габариты стержневого ящика")
        src = sinto["sources"][item["source_id"]]
        out["Стержневые машины"].append({
            "name": f"Sinto {item['model']}",
            "specs": (f"Макс. ящик {dims[0]:g}×{dims[1]:g}×{dims[2]:g} мм; "
                      f"одинарный выстрел {_verified_number(spec, 'single_shot_core_weight_kg', 'кг')}; "
                      f"двойной {_verified_number(spec, 'double_shot_core_weight_kg', 'кг')}; "
                      f"сухой цикл {_verified_number(spec, 'dry_cycle_time_s', 'с')}"),
            "conditions": "Cold-box; сухой цикл НЕ является производительностью готовых стержней",
            "source": src["document_title"] + ", " + item["source_reference"]["location"],
            "url": src["url"],
            "status": "Параметры из каталога; пригодность для проекта не проверена",
        })
    sources = {s["id"]: s for s in grades["sources"]}
    for item in grades["grades"]:
        if item.get("verification_status") != "verified_designation_only":
            continue
        src = sources[item["standard_id"]]
        aliases = item.get("aliases", [])
        title = item["name"] + (f" ({', '.join(aliases)})" if aliases else "")
        qualification = ("По требованию потребителя. "
                         if item.get("customer_request_only") else "")
        out["Марки материалов"].append({
            "name": title,
            "specs": f"{src['designation']}; {item['group']}",
            "conditions": (qualification +
                           "Подтверждено только обозначение марки. "
                           "Плотность, усадка и температуры НЕ подтверждены."),
            "source": f"{src['title']}, {item['evidence']}",
            "url": src["url"],
            "text_url": src["text_url"],
            "status": "Нормативное обозначение, не технологические параметры",
        })
    return out
