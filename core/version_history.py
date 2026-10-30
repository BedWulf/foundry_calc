"""History of previous successful project saves; independent from crash recovery."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import os
from pathlib import Path
import re
import tempfile
from uuid import uuid4

from config import USER_DATA_DIR
from .project_io import LoadedProject, ProjectFileError, read_project

_PATTERN = re.compile(r"^version-(\d{8}T\d{12}Z-[0-9a-f]{32})\.fpro\.json$")
_ID = re.compile(r"^\d{8}T\d{12}Z-[0-9a-f]{32}$")


@dataclass(frozen=True)
class VersionEntry:
    snapshot_id: str
    file_path: Path
    source_path: Path
    project_name: str
    saved_at: datetime
    castings_count: int


class VersionHistoryStore:
    """Copies the OLD file before Save overwrites it. Never prunes versions."""

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root is not None else USER_DATA_DIR / "history"

    def _directory(self, source_path: Path) -> Path:
        source = os.path.normcase(str(Path(source_path).resolve()))
        return self.root / sha256(source.encode("utf-8")).hexdigest()[:32]

    def path_for(self, source_path: Path, snapshot_id: str) -> Path:
        if not _ID.fullmatch(snapshot_id):
            raise ProjectFileError("Недопустимый идентификатор версии")
        return self._directory(source_path) / f"version-{snapshot_id}.fpro.json"

    def _entry(self, source_path: Path, filename: Path) -> VersionEntry:
        match = _PATTERN.fullmatch(filename.name)
        if match is None or filename.parent != self._directory(source_path):
            raise ProjectFileError("Версия не относится к исходному проекту")
        loaded = read_project(filename)
        date = datetime.strptime(
            match.group(1)[:22], "%Y%m%dT%H%M%S%fZ"
        ).replace(tzinfo=timezone.utc)
        return VersionEntry(
            match.group(1), filename, Path(source_path).resolve(),
            loaded.project.name, date, len(loaded.project.castings),
        )

    def preserve_before_save(self, source_path: Path) -> VersionEntry | None:
        """Archive validated current bytes; abort overwrite on any error."""
        source = Path(source_path).resolve()
        if not source.exists():
            return None
        read_project(source)
        content = source.read_bytes()
        folder = self._directory(source)
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        filename = self.path_for(source, f"{stamp}-{uuid4().hex}")
        fd, temp = tempfile.mkstemp(prefix=".history-", suffix=".tmp", dir=folder)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            read_project(Path(temp))
            os.replace(temp, filename)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        return self._entry(source, filename)

    def list_versions(self, source_path: Path) -> list[VersionEntry]:
        source = Path(source_path).resolve()
        folder = self._directory(source)
        if not folder.is_dir():
            return []
        versions = []
        for filename in folder.glob("version-*.fpro.json"):
            try:
                versions.append(self._entry(source, filename))
            except (OSError, ValueError, TypeError):
                continue  # Preserve damaged snapshots for diagnosis.
        return sorted(versions, key=lambda v: v.snapshot_id, reverse=True)

    def load_version(self, entry: VersionEntry) -> LoadedProject:
        if (entry.source_path != entry.source_path.resolve()
                or entry.file_path != self.path_for(entry.source_path, entry.snapshot_id)):
            raise ProjectFileError("Недопустимый путь к сохранённой версии")
        return read_project(entry.file_path)
