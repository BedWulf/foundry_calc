"""Изолированное автосохранение для аварийного восстановления проекта.

Снимки не перезаписывают исходный *.fpro.json. Каждая открытая
редакторская сессия имеет собственный UUID; два диплома не смешиваются.
Восстановление запускается только с согласия пользователя.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from config import USER_DATA_DIR
from .project import Project
from .project_io import (
    LoadedProject, ProjectFileError, read_project, write_project,
)

_RECOVERY_NAME = re.compile(r"^recovery-([0-9a-f]{32})\.fpro\.json$")
MAX_RECOVERY_FILES_TO_SCAN = 100


@dataclass(frozen=True)
class RecoveryEntry:
    """Metadata from a validated crash-recovery snapshot."""
    snapshot_id: str
    file_path: Path
    project_name: str
    saved_at: datetime
    original_path: Path | None
    original_mtime_ns: int | None
    castings_count: int


class RecoveryStore:
    def __init__(self, root: Path | None = None):
        self.root = (
            Path(root) if root is not None else USER_DATA_DIR / "recovery"
        )

    @staticmethod
    def new_session_id() -> str:
        return uuid4().hex

    def path_for(self, snapshot_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", snapshot_id):
            raise ProjectFileError("Недопустимый идентификатор резервной копии")
        return self.root / f"recovery-{snapshot_id}.fpro.json"

    def save_snapshot(
        self,
        snapshot_id: str,
        project: Project,
        choices: dict[str, Any],
        custom_catalogs: dict[str, Any],
        original_path: Path | None = None,
    ) -> Path:
        """Atomically save a DIRTY project; caller controls dirty detection.

        Never writes to the user's original project file. Even when source
        and recovery root are on the same volume, path_for is independent.
        """
        filename = self.path_for(snapshot_id)
        source = Path(original_path).resolve() if original_path else None
        mtime = None
        if source is not None:
            try:
                mtime = source.stat().st_mtime_ns
            except OSError:
                pass
        meta = {
            "snapshot_id": snapshot_id,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "original_path": str(source) if source else None,
            "original_mtime_ns": mtime,
        }
        write_project(
            filename, project, choices, custom_catalogs,
            recovery_metadata=meta,
        )
        return filename

    @staticmethod
    def _read_entry(path: Path) -> RecoveryEntry:
        # Validate full payload before showing it as recoverable.
        loaded = read_project(path)
        document = json.loads(path.read_text(encoding="utf-8"))
        meta = document.get("recovery")
        if not isinstance(meta, dict):
            raise ProjectFileError("Нет метаданных восстановления")
        expected = _RECOVERY_NAME.fullmatch(path.name)
        if expected is None or meta.get("snapshot_id") != expected.group(1):
            raise ProjectFileError("Идентификатор снимка не совпадает с именем")
        if not isinstance(meta.get("saved_at"), str):
            raise ProjectFileError("Нет даты резервной копии")
        try:
            dt = datetime.fromisoformat(meta["saved_at"])
        except ValueError as exc:
            raise ProjectFileError("Неверная дата резервной копии") from exc
        if dt.tzinfo is None:
            raise ProjectFileError("Нет временной зоны резервной копии")
        original = meta.get("original_path")
        if original is not None and (
                not isinstance(original, str) or not Path(original).is_absolute()):
            raise ProjectFileError("Неверный путь исходного проекта")
        source_mtime = meta.get("original_mtime_ns")
        if source_mtime is not None and (
                type(source_mtime) is not int or source_mtime < 0):
            raise ProjectFileError("Неверное время исходного проекта")
        return RecoveryEntry(
            snapshot_id=expected.group(1),
            file_path=path,
            project_name=loaded.project.name,
            saved_at=dt,
            original_path=Path(original) if original else None,
            original_mtime_ns=source_mtime,
            castings_count=len(loaded.project.castings),
        )

    def list_snapshots(self) -> list[RecoveryEntry]:
        """Newest first; corrupted copies are left on disk, never deleted."""
        if not self.root.is_dir():
            return []
        entries: list[RecoveryEntry] = []
        # Prioritise newest snapshots even after dozens of crashed sessions.
        # A lexicographical UUID ordering could hide the freshest entry.
        def newest(path: Path) -> int:
            try:
                return path.stat().st_mtime_ns
            except OSError:
                return 0
        files = sorted(
            self.root.glob("recovery-*.fpro.json"),
            key=newest, reverse=True)[:MAX_RECOVERY_FILES_TO_SCAN]
        for path in files:
            try:
                entries.append(self._read_entry(path))
            except (OSError, ValueError, TypeError):
                continue
        entries.sort(key=lambda x: x.saved_at, reverse=True)
        return entries

    def load_snapshot(
        self, entry: RecoveryEntry
    ) -> tuple[LoadedProject, Path | None, bool]:
        """Return snapshot, safe original path and external-change flag.

        If user edited/moved the original while app was closed, recovery is
        deliberately untitled; Ctrl+S cannot silently overwrite that file.
        """
        if entry.file_path != self.path_for(entry.snapshot_id):
            raise ProjectFileError("Снимок вне каталога восстановления")
        fresh_entry = self._read_entry(entry.file_path)
        loaded = read_project(entry.file_path)
        source = fresh_entry.original_path
        changed = False
        if source is not None:
            try:
                current_mtime = source.stat().st_mtime_ns
                if fresh_entry.original_mtime_ns != current_mtime:
                    changed = True
                    source = None
            except OSError:
                changed = True
                source = None
        return loaded, source, changed

    def delete_snapshot(self, snapshot_id: str) -> None:
        """Delete only the selected recovery copy, never the original."""
        self.path_for(snapshot_id).unlink(missing_ok=True)
