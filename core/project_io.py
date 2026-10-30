"""Самостоятельный, переносимый, проверяемый файл проекта ЛитейныйЦех PRO.

*.fpro.json — это JSON, а не сериализованный Python/pickle.
Данные пользователя пишутся атомарно, исходные файлы НЕ перезаписываются
при ошибке. Все поля CastingItem сохраняются без преобразования единиц.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from datetime import date
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any

from .casting_item import CastingItem
from .project import Project


FORMAT = "liteynyi-tseh-project"
VERSION = 1
FILE_EXTENSION = ".fpro.json"
# Derived quantities are recalculated when the project is opened, never
# trusted as an engineering result loaded from an old file.
DERIVED_FIELDS = frozenset({
    "F_calendar_h", "F_nominal_h", "F_equipment_h", "F_workers_h",
    "metal_charge_t", "liquid_metal_t",
})


class ProjectFileError(ValueError):
    """Некорректная или неподдерживаемая запись проекта."""


@dataclass
class LoadedProject:
    project: Project
    choices: dict[str, Any]
    custom_catalogs: dict[str, Any]


# Only application-owned custom equipment files, not arbitrary user paths.
CUSTOM_CATALOG_FILES = frozenset({
    "custom_furnaces.json",
    "custom_molding_lines.json",
    "custom_core_machines.json",
    "custom_mixers.json",
    "custom_cleaning_machines.json",
    "custom_warehouses.json",
    "custom_transport.json",
})


def _check_numbers(obj: Any, location: str = "project") -> None:
    if isinstance(obj, float) and not math.isfinite(obj):
        raise ProjectFileError(f"{location}: число не является конечным")
    if isinstance(obj, dict):
        for k, value in obj.items():
            if not isinstance(k, str):
                raise ProjectFileError(f"{location}: имя поля не является строкой")
            _check_numbers(value, f"{location}.{k}")
    if isinstance(obj, list):
        for i, value in enumerate(obj):
            _check_numbers(value, f"{location}[{i}]")


def project_inputs(project: Project) -> dict[str, Any]:
    """Входные данные + вся номенклатура, но без устаревающих результатов."""
    data = asdict(project)
    data["created_at"] = project.created_at.isoformat()
    for key in DERIVED_FIELDS:
        data.pop(key, None)
    return data


def _validate_project(data: Any) -> Project:
    if not isinstance(data, dict):
        raise ProjectFileError("Блок project должен быть объектом")
    allowed = {f.name for f in fields(Project)}
    missing = {"name", "created_at", "castings", "annual_output_t"} - data.keys()
    if missing:
        raise ProjectFileError("В проекте отсутствуют поля: " + ", ".join(sorted(missing)))
    extras = data.keys() - allowed
    if extras:
        raise ProjectFileError("Неизвестные поля проекта: " + ", ".join(sorted(extras)))
    payload = dict(data)
    if not isinstance(payload["created_at"], str):
        raise ProjectFileError("created_at должен быть датой в формате YYYY-MM-DD")
    try:
        payload["created_at"] = date.fromisoformat(payload["created_at"])
    except ValueError as exc:
        raise ProjectFileError("Некорректная дата создания") from exc
    if not isinstance(payload.get("name"), str):
        raise ProjectFileError("Название проекта должно быть строкой")
    for key in ("annual_output_t", "shift_duration_h", "molding_setup_h"):
        val = payload.get(key)
        if val is not None and (type(val) not in (int, float) or val < 0):
            raise ProjectFileError(f"Недопустимое значение {key}")
    if payload.get("molding_park_mode", "auto") not in ("auto", "manual"):
        raise ProjectFileError("Неизвестный режим формирования парка")
    counts = payload.get("molding_line_counts", {})
    if not isinstance(counts, dict) or any(
        not isinstance(k, str) or type(v) is not int or v < 0 or v > 10000
        for k, v in counts.items()
    ):
        raise ProjectFileError("Некорректный список ручных формовочных линий")
    castings = payload["castings"]
    if not isinstance(castings, list) or len(castings) > 100000:
        raise ProjectFileError("Номенклатура должна быть списком до 100 000 строк")
    allowed_casting = {f.name for f in fields(CastingItem)}
    result = []
    for index, raw in enumerate(castings, 1):
        if not isinstance(raw, dict) or raw.keys() - allowed_casting:
            raise ProjectFileError(f"Строка отливки №{index}: неизвестные поля")
        try:
            item = CastingItem(**raw)
        except (TypeError, ValueError) as exc:
            raise ProjectFileError(f"Ошибка строки отливки №{index}: {exc}") from exc
        if not isinstance(item.name, str) or (
            type(item.molds_per_year) is not int or item.molds_per_year < 0):
            raise ProjectFileError(f"Недопустимые значения отливки №{index}")
        result.append(item)
    payload["castings"] = result
    try:
        project = Project(**payload)
    except (TypeError, ValueError) as exc:
        raise ProjectFileError(f"Не удалось восстановить проект: {exc}") from exc
    return project


def make_document(
    project: Project, choices: dict[str, Any] | None = None,
    custom_catalogs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = {
        "format": FORMAT, "version": VERSION,
        "project": project_inputs(project),
        "choices": choices if choices is not None else {},
        "custom_catalogs": custom_catalogs if custom_catalogs is not None else {},
    }
    _check_numbers(data)
    return data


def read_project(path: Path) -> LoadedProject:
    file = Path(path)
    if file.stat().st_size > 80 * 1024 * 1024:
        raise ProjectFileError("Слишком большой файл проекта (максимум 80 МБ)")
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ProjectFileError("Файл проекта повреждён или не является JSON") from exc
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ProjectFileError("Это не файл проекта ЛитейныйЦех PRO")
    if type(data.get("version")) is not int or data["version"] != VERSION:
        raise ProjectFileError(
            f"Версия файла {data.get('version')} не поддерживается "
            f"(программа читает версию {VERSION})")
    _check_numbers(data)
    project = _validate_project(data.get("project"))
    choices = data.get("choices", {})
    catalogs = data.get("custom_catalogs", {})
    if not isinstance(choices, dict) or not isinstance(catalogs, dict):
        raise ProjectFileError("Некорректный блок выборов или справочников")
    for k, v in choices.items():
        if not isinstance(k, str) or not isinstance(v, dict):
            raise ProjectFileError("Повреждён выбор оборудования")
    if any(k not in CUSTOM_CATALOG_FILES for k in catalogs):
        raise ProjectFileError("Неизвестный пользовательский справочник")
    return LoadedProject(project, choices, catalogs)


def write_project(
    path: Path, project: Project, choices: dict[str, Any] | None = None,
    custom_catalogs: dict[str, Any] | None = None,
) -> Path:
    file = Path(path)
    data = make_document(project, choices, custom_catalogs)
    # Validate the full snapshot before overwriting any existing project.
    _validate_project(data["project"])
    text = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)
    file.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".fpro-", suffix=".tmp", dir=str(file.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as output:
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp, file)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return file


def read_custom_catalogs(user_dir: Path) -> dict[str, Any]:
    """Attach only existing application custom catalogues to the project."""
    out = {}
    for filename in sorted(CUSTOM_CATALOG_FILES):
        p = Path(user_dir) / filename
        if p.is_file():
            try:
                out[filename] = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise ProjectFileError(f"Повреждён пользовательский справочник {filename}") from exc
    return out


def plan_custom_catalog_restore(user_dir: Path, catalogs: dict[str, Any]) -> dict[Path, Any]:
    """Prepare safe merges without writing any file or overwriting local IDs.

    Existing custom equipment wins unless both copies are identical. A
    different definition for the same ID is rejected, not silently replaced.
    """
    pending = {}
    for filename, imported in catalogs.items():
        if filename not in CUSTOM_CATALOG_FILES:
            raise ProjectFileError(f"Недопустимый справочник: {filename}")
        path = Path(user_dir) / filename
        if path.is_file():
            try:
                current = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise ProjectFileError(f"Невозможно прочитать {filename}") from exc
        else:
            current = None
        if current is None:
            pending[path] = imported
            continue
        if current == imported:
            continue
        # Both list and {version, items:[]} catalogs are in use.
        if isinstance(current, list) and isinstance(imported, list):
            key = None
            existing, incoming = current, imported
        elif isinstance(current, dict) and isinstance(imported, dict):
            lists = [k for k, v in imported.items()
                     if isinstance(v, list) and isinstance(current.get(k), list)]
            if len(lists) != 1:
                raise ProjectFileError(f"Конфликт структуры справочника {filename}")
            key = lists[0]
            if any(k != key and current.get(k) != v for k, v in imported.items()):
                raise ProjectFileError(f"Конфликт метаданных справочника {filename}")
            existing, incoming = current[key], imported[key]
        else:
            raise ProjectFileError(f"Разные форматы справочника {filename}")
        by_id = {}
        for item in existing:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                raise ProjectFileError(f"Некорректная запись в {filename}")
            by_id[item["id"]] = item
        merged = list(existing)
        for item in incoming:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                raise ProjectFileError(f"Некорректная запись в {filename}")
            previous = by_id.get(item["id"])
            if previous is None:
                merged.append(item)
                by_id[item["id"]] = item
            elif previous != item:
                raise ProjectFileError(
                    f"Оборудование {item['id']} различается в {filename}; "
                    "импорт отменён во избежание перезаписи")
        if key is None:
            pending[path] = merged
        else:
            pending[path] = {**current, key: merged}
    return pending


def restore_custom_catalogs(pending: dict[Path, Any]) -> None:
    """Atomically write each previously validated catalog without deletions."""
    for path, data in pending.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix=".catalog-", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
            os.replace(temp, path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
