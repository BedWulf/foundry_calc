"""Сохранение и загрузка выборов пользователя."""
import json
import os
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime


class UserChoices:
    """Управление выборами оборудования и материалов пользователем."""

    def __init__(self, base_dir: Optional[Path] = None):
        if base_dir is None:
            from config import USER_DATA_DIR
            self.choices_dir = USER_DATA_DIR
        else:
            self.choices_dir = Path(base_dir) / "user_data"
        self.choices_dir.mkdir(parents=True, exist_ok=True)
        self.choices_file = self.choices_dir / "choices.json"
        self._data: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        """Загрузить выборы из файла."""
        if self.choices_file.exists():
            try:
                with open(self.choices_file, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            except (json.JSONDecodeError, IOError):
                self._data = {}

    def _save(self) -> None:
        """Атомарно сохранить выборы без риска обрезать choices.json."""
        self.choices_dir.mkdir(parents=True, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(
            prefix=".choices-", suffix=".tmp", dir=str(self.choices_dir))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                json.dump(self._data, output, indent=2, ensure_ascii=False)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temp_path, self.choices_file)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def get_choice(self, project_id: str, category: str) -> Optional[Dict[str, Any]]:
        """Получить выбор для проекта."""
        project_choices = self._data.get(project_id, {})
        return project_choices.get(category)

    def set_choice(
        self,
        project_id: str,
        category: str,
        choice_data: Dict[str, Any],
    ) -> None:
        """Сохранить выбор."""
        if project_id not in self._data:
            self._data[project_id] = {}
        
        self._data[project_id][category] = {
            **choice_data,
            "updated_at": datetime.now().isoformat(),
        }
        self._save()

    def get_project_choices(self, project_id: str) -> Dict[str, Any]:
        """Получить все выборы для проекта."""
        return self._data.get(project_id, {})

    def replace_project_choices(self, project_id: str, choices: Dict[str, Any]) -> None:
        """Restore choices from a verified project archive.

        Other project records and unrelated global preferences remain intact.
        A snapshot from the archive is authoritative for its project ID.
        """
        if not isinstance(choices, dict):
            raise ValueError("Выбор оборудования должен быть словарём")
        self._data[project_id] = dict(choices)
        self._save()

    def clear_project_choices(self, project_id: str) -> None:
        """Очистить выборы для проекта."""
        if project_id in self._data:
            del self._data[project_id]
            self._save()

    def get_selected_alloy(self, project_id: str) -> Optional[str]:
        """Получить выбранный сплав для проекта."""
        choice = self.get_choice(project_id, "alloy")
        return choice.get("alloy_id") if choice else None

    # ---------- удобное API для оборудования (Шаг 2) ----------
    EQUIPMENT_CATEGORY: str = "melting_furnace"
    #: Категория для выбора формовочной линии (Раздел 4, вкладка «Формовочное»)
    MOLDING_LINE_CATEGORY: str = "molding_line"
    #: Категория для выбора стержневой машины (Раздел 5, вкладка «Стержневое»)
    CORE_MACHINE_CATEGORY: str = "core_machine"
    #: Категория очистного отделения (Раздел 7). Внутри хранится словарь
    #: подкатегорий по позициям техпроцесса: ``{"shot_blasting": {...}}`` —
    #: там оборудования много, и для каждой позиции нужен свой выбор.
    CLEANING_CATEGORY: str = "cleaning_equipment"
    #: Категория смесеприготовительного отделения (Раздел 6). Хранит
    #: подсловарь по операциям: ``{"molding_mix": {...}, "sieving": {...}}``.
    SAND_PREP_CATEGORY: str = "sand_prep_equipment"
    #: Категория складского хозяйства (Раздел 8/10). Хранит подсловарь по
    #: ключам складов: ``{"charge": {...}, "molding_sand": {...}, ...}``.
    WAREHOUSE_CATEGORY: str = "warehouse_units"
    #: Транспорт: позиции ``ladle`` (ковш) и ``crane`` (мостовой кран)
    TRANSPORT_CATEGORY: str = "transport_units"

    def save_equipment_choice(
        self,
        project_id: str,
        equipment_data: Dict[str, Any],
        category: Optional[str] = None,
    ) -> None:
        """Сохранить выбранную единицу оборудования для проекта.

        Args:
            project_id: идентификатор проекта (Project.project_id)
            equipment_data: карточка оборудования из селектора/калькулятора
                (обязателен ключ "id")
            category: категория выбора; по умолчанию ``EQUIPMENT_CATEGORY``
                (плавильные печи). Для формовочных линий передавайте
                ``MOLDING_LINE_CATEGORY``
        """
        payload = {
            "equipment_id": equipment_data.get("id", ""),
            "name": equipment_data.get("name", ""),
            "type": equipment_data.get("type", ""),
            "num_required": equipment_data.get("_num_required"),
            "load_factor": equipment_data.get("_load_factor"),
        }
        self.set_choice(project_id, category or self.EQUIPMENT_CATEGORY, payload)

    def get_equipment_choice(
        self,
        project_id: str,
        category: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Загрузить сохранённый выбор оборудования (или None).

        Args:
            project_id: идентификатор проекта
            category: категория выбора (по умолчанию — плавильные печи)

        Returns:
            Словарь с полями equipment_id/name/type/num_required/load_factor
            либо None, если выбор не сохранялся
        """
        return self.get_choice(project_id, category or self.EQUIPMENT_CATEGORY)
    # ---------- оборудование с подкатегориями (очистное отделение) ----------
    def save_operation_choice(
        self,
        project_id: str,
        category: str,
        operation_key: str,
        equipment_data: Dict[str, Any],
    ) -> None:
        """Сохранить выбор оборудования для одной позиции техпроцесса.

        Позиции внутри ``category`` хранятся как подсловарь по ключу
        ``operation_key`` — так в ``choices.json`` умещается весь парк
        очистного отделения (охлаждение, выбивка, дробемёт, обрубка,
        зачистка, термообработка).

        Args:
            project_id: идентификатор проекта
            category: категория (например ``CLEANING_CATEGORY``)
            operation_key: ключ позиции (``shot_blasting`` и т.п.)
            equipment_data: карточка выбранного оборудования
        """
        stored = dict(self.get_choice(project_id, category) or {})
        stored[operation_key] = {
            "equipment_id": equipment_data.get("id", ""),
            "name": equipment_data.get("name", ""),
            "type": equipment_data.get("type", ""),
            "num_required": equipment_data.get("_num_required"),
            "load_factor": equipment_data.get("_load_factor"),
        }
        self.set_choice(project_id, category, stored)

    def get_operation_choices(
        self,
        project_id: str,
        category: str,
    ) -> Dict[str, str]:
        """Загрузить сохранённые id оборудования по всем позициям категории.

        Args:
            project_id: идентификатор проекта
            category: категория (например ``CLEANING_CATEGORY``)

        Returns:
            Словарь ``{operation_key: equipment_id}`` (пустой, если выборов нет)
        """
        stored = self.get_choice(project_id, category) or {}
        result: Dict[str, str] = {}
        for key, value in stored.items():
            if isinstance(value, dict) and value.get("equipment_id"):
                result[key] = str(value["equipment_id"])
        return result
