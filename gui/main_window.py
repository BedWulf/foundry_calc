"""Главное окно приложения с боковой навигацией."""
from pathlib import Path
from uuid import uuid4
import json
from shutil import copyfile

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPalette, QColor, QAction, QKeySequence
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QStackedWidget, QPushButton, QLabel, QFrame, QScrollArea,
    QMessageBox, QFileDialog, QApplication,
)

from config import APP_NAME, APP_VERSION, COLORS, THEME_QSS, EXAMPLES_DIR
from core.project import Project
from core.recovery import RecoveryStore, RecoveryEntry
from core.version_history import VersionHistoryStore, VersionEntry
from gui.dialogs.version_history_dialog import VersionHistoryDialog
from gui.dialogs.recovery_dialog import RecoveryDialog
from core.user_choices import UserChoices
from core.project_io import (
    FILE_EXTENSION, ProjectFileError, project_inputs, read_project,
    write_project, read_custom_catalogs, plan_custom_catalog_restore,
    restore_custom_catalogs,
)
from config import USER_DATA_DIR
from core.onboarding import OnboardingState, TUTORIAL_STEPS
from core.tutorial_example import save_tutorial_excel

# Импорты реальных вкладок
from gui.tabs.project_tab import ProjectTab
from gui.tabs.time_funds_tab import TimeFundsTab
from gui.tabs.melting_tab import MeltingTab
from gui.tabs.molding_tab import MoldingTab
from gui.tabs.core_tab import CoreTab
from gui.tabs.sand_tab import SandTab
from gui.tabs.cleaning_tab import CleaningTab
from gui.tabs.warehouse_tab import WarehouseTab
from gui.tabs.workforce_tab import WorkforceTab
from gui.tabs.areas_tab import AreasTab
from gui.tabs.transport_tab import TransportTab
from gui.tabs.summary_tab import SummaryTab
from gui.tabs.help_tab import HelpTab


class SideBarButton(QPushButton):
    """Кнопка боковой навигации."""

    def __init__(self, text: str, index: int, parent=None):
        super().__init__(text, parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setProperty("nav_index", index)
        self.setMinimumHeight(48)
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['bg_panel']};
                color: {COLORS['text_primary']};
                border: none;
                text-align: left;
                padding: 10px 16px;
                font-size: 14px;
                font-weight: bold;
                border-left: 3px solid transparent;
            }}
            QPushButton:hover {{
                background-color: #2E3B4C;
                border-left: 3px solid {COLORS['accent']};
            }}
            QPushButton:checked {{
                background-color: #344255;
                border-left: 3px solid {COLORS['accent']};
                color: {COLORS['accent']};
            }}
        """)


class MainWindow(QMainWindow):
    """Главное окно приложения."""

    SECTIONS = [
        ("📋 Исходные данные",    "project_tab"),
        ("⏱ Фонды времени",       "time_funds_tab"),
        (" Плавильное",         "melting_tab"),
        ("🏭 Формовочное",        "molding_tab"),
        (" Стержневое",         "core_tab"),
        ("⚙️ Смесеприготовит.",   "sand_tab"),
        (" Обрубка/Очистка",    "cleaning_tab"),
        ("📦 Склады",             "warehouse_tab"),
        ("👷 Рабочая сила",       "workforce_tab"),
        ("📐 Площади",            "areas_tab"),
        ("🚛 Транспорт",          "transport_tab"),
        ("📊 Сводка",             "summary_tab"),
        ("❓ Руководство",        "help_tab"),
    ]

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.setMinimumSize(1000, 680)
        self.resize(1600, 960)

        # Модель проекта (единая для всех вкладок)
        self.project = Project()
        self._onboarding = OnboardingState()
        self._startup_offer_checked = False
        self._tour_index = -1
        self._tour_origin = 0
        self._project_path: Path | None = None
        self._choice_origin_project_id = self.project.project_id
        self._saved_signature: str = ""
        self._autosave_ready = False
        self._recovery_store = RecoveryStore()
        self._version_history = VersionHistoryStore()
        self._recovery_id = RecoveryStore.new_session_id()
        self._autosave_last_signature: str | None = None
        self._autosave_periodic = QTimer(self)
        self._autosave_periodic.setInterval(60_000)
        self._autosave_periodic.timeout.connect(self._autosave_snapshot)
        self._autosave_debounce = QTimer(self)
        self._autosave_debounce.setSingleShot(True)
        self._autosave_debounce.setInterval(12_000)
        self._autosave_debounce.timeout.connect(self._autosave_snapshot)

        self._apply_theme()
        self._build_file_menu()
        self._build_ui()
        self._connect_signals()
        self._select_section(0)
        self._saved_signature = self._project_signature()
        self._update_project_title()
        self._autosave_ready = True
        self._autosave_periodic.start()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ── Боковая панель ──
        self.sidebar = QFrame()
        self.sidebar.setFixedWidth(235)
        self.sidebar.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['bg_panel']};
                border-right: 2px solid {COLORS['separator']};
            }}
        """)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)

        header = QLabel(APP_NAME)
        header.setAlignment(Qt.AlignCenter)
        header.setMinimumHeight(80)
        header.setStyleSheet(f"""
            QLabel {{
                color: {COLORS['accent']};
                font-size: 18px;
                font-weight: bold;
                background-color: {COLORS['bg_main']};
                border-bottom: 2px solid {COLORS['separator']};
            }}
        """)
        sidebar_layout.addWidget(header)

        self.nav_buttons: list[SideBarButton] = []
        for idx, (title, _) in enumerate(self.SECTIONS):
            btn = SideBarButton(title, idx)
            btn.clicked.connect(lambda checked, i=idx: self._select_section(i))
            sidebar_layout.addWidget(btn)
            self.nav_buttons.append(btn)

        sidebar_layout.addStretch()

        version_lbl = QLabel(f"v{APP_VERSION}")
        version_lbl.setAlignment(Qt.AlignCenter)
        version_lbl.setStyleSheet(f"""
            QLabel {{
                color: {COLORS['text_secondary']};
                font-size: 11px;
                padding: 8px;
                background-color: {COLORS['bg_main']};
            }}
        """)
        sidebar_layout.addWidget(version_lbl)

        # ── Область контента ─
        self.content_stack = QStackedWidget()
        self.content_stack.setStyleSheet(f"""
            QStackedWidget {{
                background-color: {COLORS['bg_main']};
            }}
        """)

        # Создаём реальные вкладки
        self.tabs: dict[str, QWidget] = {}
        for title, key in self.SECTIONS:
            tab = self._create_tab(key, title)
            self.content_stack.addWidget(tab)
            self.tabs[key] = tab

        root_layout.addWidget(self.sidebar)
        content_panel = QWidget()
        content_layout = QVBoxLayout(content_panel)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # Non-modal guided tour: the real input tabs remain accessible.
        self.tour_banner = QFrame()
        self.tour_banner.setStyleSheet(
            f"QFrame {{ background: {COLORS['bg_panel']}; "
            f"border-bottom: 2px solid {COLORS['accent']}; }}"
            f"QLabel {{ color: {COLORS['text_primary']}; border: none; }}"
        )
        tour_layout = QVBoxLayout(self.tour_banner)
        tour_layout.setContentsMargins(14, 10, 14, 10)
        self.tour_heading = QLabel()
        self.tour_heading.setStyleSheet(
            f"color: {COLORS['accent']}; font-weight: bold;")
        self.tour_instruction = QLabel()
        self.tour_instruction.setWordWrap(True)
        tour_layout.addWidget(self.tour_heading)
        tour_layout.addWidget(self.tour_instruction)
        tour_controls = QHBoxLayout()
        self.tour_back_button = QPushButton("← Назад")
        self.tour_next_button = QPushButton("Далее →")
        self.tour_close_button = QPushButton("Прервать обучение")
        self.tour_example_button = QPushButton("Создать учебный Excel")
        self.tour_example_button.clicked.connect(self._save_tutorial_example)
        self.tour_back_button.clicked.connect(self._tour_back)
        self.tour_next_button.clicked.connect(self._tour_next)
        self.tour_close_button.clicked.connect(self._stop_tutorial)
        tour_controls.addWidget(self.tour_back_button)
        tour_controls.addWidget(self.tour_next_button)
        tour_controls.addStretch()
        tour_controls.addWidget(self.tour_example_button)
        tour_controls.addWidget(self.tour_close_button)
        tour_layout.addLayout(tour_controls)
        self.tour_banner.hide()

        file_toolbar = QHBoxLayout()
        file_toolbar.setContentsMargins(12, 8, 12, 8)
        self.btn_new_project = QPushButton("Новый")
        self.btn_open_project = QPushButton("Открыть проект")
        self.btn_save_project = QPushButton("Сохранить")
        self.btn_save_as_project = QPushButton("Сохранить как…")
        for btn, handler in (
            (self.btn_new_project, self._new_project),
            (self.btn_open_project, self._open_project),
            (self.btn_save_project, self._save_project),
            (self.btn_save_as_project, self._save_project_as),
        ):
            btn.clicked.connect(handler)
            file_toolbar.addWidget(btn)
        file_toolbar.addStretch()
        content_layout.addLayout(file_toolbar)
        content_layout.addWidget(self.tour_banner)
        content_layout.addWidget(self.content_stack, 1)
        root_layout.addWidget(content_panel, 1)

    def _build_file_menu(self) -> None:
        """Клавиатурные команды и дублирующие кнопки панели проекта."""
        menu = self.menuBar().addMenu("Файл")
        for text, shortcut, slot in (
            ("Новый проект", "Ctrl+N", self._new_project),
            ("Открыть проект…", "Ctrl+O", self._open_project),
            ("Сохранить проект", "Ctrl+S", self._save_project),
            ("Сохранить проект как…", "Ctrl+Shift+S", self._save_project_as),
            ("История версий проекта…", "", self._show_version_history),
            ("Восстановить несохранённую работу…", "", self._show_recovery_dialog),
        ):
            action = QAction(text, self)
            if shortcut:
                action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(slot)
            menu.addAction(action)

    def _flush_pending_text_inputs(self) -> None:
        """Capture QLineEdit edits before Ctrl+S or closing the main window.

        Some fields are normally committed on editingFinished; pressing
        Ctrl+S while the cursor is still inside a field must not lose text.
        """
        tab = self.tabs.get("project_tab")
        if tab is None:
            return
        for widget, field in (
            (tab.edit_name, "name"),
            (tab.edit_customer, "customer"),
            (tab.edit_alloy, "alloy"),
        ):
            # Do not overwrite a programmatic change to the model with
            # an old text field that the user did NOT actually edit.
            if widget.isModified():
                value = widget.text().strip()
                if field == "name":
                    value = value or "Проект литейного цеха"
                setattr(self.project, field, value)
                widget.setModified(False)

    def _project_signature(self) -> str:
        """Оценка несохранённого ввода; расчётные поля не влияют."""
        choices = UserChoices().get_project_choices(self.project.project_id)
        def without_timestamps(value):
            if isinstance(value, dict):
                return {
                    k: without_timestamps(v)
                    for k, v in value.items() if k != "updated_at"
                }
            if isinstance(value, list):
                return [without_timestamps(x) for x in value]
            return value
        return json.dumps({
            "project": project_inputs(self.project),
            "choices": without_timestamps(choices),
        }, ensure_ascii=False, sort_keys=True, allow_nan=False)

    def _is_project_dirty(self) -> bool:
        tab = self.tabs.get("project_tab") if hasattr(self, "tabs") else None
        if tab is not None:
            for widget, field in (
                (tab.edit_name, "name"),
                (tab.edit_customer, "customer"),
                (tab.edit_alloy, "alloy"),
            ):
                if widget.isModified() and widget.text().strip() != str(
                        getattr(self.project, field)):
                    return True
        return self._project_signature() != self._saved_signature

    def _update_project_title(self) -> None:
        filename = (self._project_path.name if self._project_path
                    else "Без имени")
        marker = " *" if self._is_project_dirty() else ""
        self.setWindowTitle(
            f"{APP_NAME} v{APP_VERSION} — {filename}{marker}")

    def _confirm_discard_project(self) -> bool:
        """Save / discard / cancel. Failure to save blocks closing/opening."""
        self._flush_pending_text_inputs()
        if not self._is_project_dirty():
            return True
        answer = QMessageBox.question(
            self, "Несохранённые изменения",
            "В текущем проекте есть несохранённые данные.\n"
            "Сохранить их перед продолжением?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if answer == QMessageBox.Cancel:
            return False
        if answer == QMessageBox.Save:
            return self._save_project()
        return answer == QMessageBox.Discard

    def _save_project(self, _checked=False) -> bool:
        if self._project_path is None:
            return self._save_project_as()
        return self._write_project_to(self._project_path)

    def _save_project_as(self, _checked=False) -> bool:
        suggested = (str(self._project_path) if self._project_path
                     else str(Path.home() / "ЛитейныйЦех_проект.fpro.json"))
        filename, _ = QFileDialog.getSaveFileName(
            self, "Сохранить проект целиком", suggested,
            "Проект ЛитейныйЦех PRO (*.fpro.json);;JSON (*.json)",
            options=QFileDialog.DontUseNativeDialog,
        )
        if not filename:
            return False
        target = Path(filename)
        if not target.name.lower().endswith(FILE_EXTENSION):
            target = Path(str(target) + FILE_EXTENSION)
        if target.exists() and target != self._project_path:
            choice = QMessageBox.question(
                self, "Подтверждение перезаписи",
                f"Файл {target.name} уже существует. Перезаписать?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if choice != QMessageBox.Yes:
                return False
        return self._write_project_to(target)

    def _write_project_to(self, path: Path) -> bool:
        self._flush_pending_text_inputs()
        old_uid = self.project.project_uid
        choices_manager = UserChoices()

        # Legacy (pre-file) choices were keyed by name+date. Renaming a
        # project must not orphan furnace/core/cleaning selections stored
        # under its earlier name, even if editingFinished already fired.
        old_selections = choices_manager.get_project_choices(
            self._choice_origin_project_id)
        current_selections = choices_manager.get_project_choices(
            self.project.project_id)

        def merge_preferences(old, new):
            if not isinstance(old, dict) or not isinstance(new, dict):
                return new
            result = dict(old)
            for k, value in new.items():
                result[k] = (merge_preferences(result[k], value)
                             if k in result else value)
            return result

        selections = merge_preferences(old_selections, current_selections)
        # A persisted project gets a UUID. Unsaved legacy projects continue
        # using the previous name/date key until the very first save.
        if not self.project.project_uid:
            self.project.project_uid = uuid4().hex
        try:
            catalogs = read_custom_catalogs(USER_DATA_DIR)
            self._version_history.preserve_before_save(path)
            write_project(path, self.project, selections, catalogs)
            # After successful write make the stored equipment choices
            # accessible via this newly stable project ID.
            choices_manager.replace_project_choices(
                self.project.project_id, selections)
            # Tabs keep UserChoices instances. After migrating the old
            # name/date ID to a new UUID, reload them before their next edit:
            # otherwise an old cache may overwrite choices in other tabs.
            for tab in self.tabs.values():
                choice_cache = getattr(tab, "choices", None)
                if isinstance(choice_cache, UserChoices):
                    choice_cache._load()
        except (OSError, ValueError, TypeError) as exc:
            self.project.project_uid = old_uid
            QMessageBox.critical(
                self, "Не удалось сохранить проект", str(exc))
            return False
        self._project_path = path
        self._choice_origin_project_id = self.project.project_id
        self._saved_signature = self._project_signature()
        self._update_project_title()
        self._remove_active_recovery()
        return True

    def _open_project(self, _checked=False) -> None:
        if not self._confirm_discard_project():
            return
        filename, _ = QFileDialog.getOpenFileName(
            self, "Открыть ранее сохранённый проект",
            str(self._project_path.parent if self._project_path
                else Path.home()),
            "Проект ЛитейныйЦех PRO (*.fpro.json);;JSON (*.json)",
            options=QFileDialog.DontUseNativeDialog,
        )
        if filename:
            self._load_project_from_path(Path(filename))

    def _load_project_from_path(self, path: Path) -> bool:
        """Validate before touching current work. No implicit Excel import."""
        try:
            imported = read_project(path)
            pending_catalogs = plan_custom_catalog_restore(
                USER_DATA_DIR, imported.custom_catalogs)
            restore_custom_catalogs(pending_catalogs)
            UserChoices().replace_project_choices(
                imported.project.project_id, imported.choices)
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.critical(
                self, "Не удалось открыть проект",
                f"Текущие данные оставлены без изменений.\n\n{exc}")
            return False
        self._activate_project(imported.project, path)
        return True

    def _activate_project(self, project: Project,
                          path: Path | None,
                          *, recovery_id: str | None = None) -> None:
        """Rebuild ALL tabs; do not leave stale widgets pointing at old Project."""
        # Retain old crash copy until all tabs have been successfully rebuilt.
        # A Qt/widget exception during activation must not erase the fallback.
        prior_recovery_id = self._recovery_id
        self._recovery_id = recovery_id or RecoveryStore.new_session_id()
        self._autosave_last_signature = None
        self._autosave_debounce.stop()
        self.project = project
        self._project_path = path
        self._choice_origin_project_id = project.project_id
        # Existing onboarding state and its first-run marker are untouched.
        self._tour_index = -1
        self._tour_origin = 0
        self._build_ui()
        self._connect_signals()
        self._select_section(0)
        self._recalculate_dependents(with_time_funds=True)
        self._saved_signature = self._project_signature()
        self._update_project_title()
        if prior_recovery_id != self._recovery_id:
            try:
                self._recovery_store.delete_snapshot(prior_recovery_id)
            except OSError:
                pass

    def _new_project(self, _checked=False) -> None:
        if not self._confirm_discard_project():
            return
        self._activate_project(
            Project(project_uid=uuid4().hex), None)

    def closeEvent(self, event) -> None:  # noqa: N802
        # Automated offscreen Qt checks cannot answer interactive dialogs;
        # the user-facing desktop always asks before discarding a project.
        app = QApplication.instance()
        if app is not None and app.platformName() == "offscreen":
            event.accept()
        elif self._confirm_discard_project():
            event.accept()
        else:
            event.ignore()
        if event.isAccepted():
            self._autosave_periodic.stop()
            self._autosave_debounce.stop()
            self._remove_active_recovery()

    def _create_tab(self, key: str, title: str) -> QWidget:
        """Фабрика вкладок."""
        if key == "project_tab":
            return ProjectTab(self.project)
        elif key == "time_funds_tab":
            return TimeFundsTab(self.project)
        elif key == "melting_tab":
            return MeltingTab(self.project)
        elif key == "molding_tab":
            return MoldingTab(self.project)
        elif key == "core_tab":
            return CoreTab(self.project)
        elif key == "sand_tab":
            return SandTab(self.project)
        elif key == "cleaning_tab":
            return CleaningTab(self.project)
        elif key == "warehouse_tab":
            return WarehouseTab(self.project)
        elif key == "workforce_tab":
            return WorkforceTab(self.project)
        elif key == "areas_tab":
            return AreasTab(self.project)
        elif key == "transport_tab":
            return TransportTab(self.project)
        elif key == "help_tab":
            return HelpTab()
        elif key == "summary_tab":
            tab = SummaryTab(self.project)
            # Поставщик сводок всех отделений (см. department_summaries)
            tab.summaries_provider = self.department_summaries
            return tab

        # Заглушка для нереализованных вкладок
        return self._make_placeholder(title)

    def _make_placeholder(self, title: str) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setAlignment(Qt.AlignCenter)
        lbl = QLabel(f" {title}\n\nБудет реализовано на соответствующем шаге.")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(f"""
            QLabel {{
                color: {COLORS['text_primary']};
                font-size: 22px;
                font-weight: bold;
            }}
        """)
        layout.addWidget(lbl)
        return w

    @staticmethod
    def _choice_signal(tab: object):
        """Вернуть сигнал смены выбора оборудования вкладки.

        Вкладки называют сигнал по-разному (``equipment_choice_changed``,
        ``line_choice_changed``, ``furnace_choice_changed``,
        ``machine_choice_changed``); метод унифицирует подключение
        реактивных связок в главном окне.

        Args:
            tab: вкладка или ``None``

        Returns:
            Привязанный сигнал либо ``None``, если у вкладки нет
            ни одного из известных сигналов выбора
        """
        if tab is None:
            return None
        for name in ("equipment_choice_changed", "line_choice_changed",
                     "furnace_choice_changed", "machine_choice_changed"):
            sig = getattr(tab, name, None)
            if sig is not None and hasattr(sig, "connect"):
                return sig
        return None

    def _recalculate_dependents(self, with_time_funds: bool = False) -> None:
        """One ordered recalculation, no recursive signal storm.

        Setting equipment options programmatically can emit a Qt selection
        signal. Blocking each dependent tab while refreshing prevents
        auto-selection from recursively refreshing other departments.
        Explicit user actions still trigger a fresh topological pass.
        """
        if getattr(self, "_recalculate_active", False):
            return
        self._recalculate_active = True
        try:
            order = (
                ["time_funds_tab"] if with_time_funds else []
            ) + [
                "melting_tab", "molding_tab", "core_tab", "sand_tab",
                "cleaning_tab", "workforce_tab", "warehouse_tab",
                "areas_tab", "transport_tab", "summary_tab",
            ]
            for key in order:
                tab = self.tabs.get(key)
                if tab is None:
                    continue
                was_blocked = tab.blockSignals(True)
                try:
                    if key == "time_funds_tab":
                        tab.on_project_changed()
                    elif callable(getattr(tab, "refresh", None)):
                        tab.refresh()
                finally:
                    tab.blockSignals(was_blocked)
        finally:
            self._recalculate_active = False
            if getattr(self, "_saved_signature", ""):
                self._update_project_title()
                self._schedule_autosave()

    def _connect_signals(self) -> None:
        """One-way updates rather than cyclic pairwise Qt connections."""
        workers = self.tabs.get("workforce_tab")
        if workers is not None:
            workers.set_dependencies_provider(self.department_summaries)

        help_tab = self.tabs.get("help_tab")
        if help_tab is not None:
            help_tab.tutorial_requested.connect(self.start_tutorial)
            help_tab.example_requested.connect(self._save_tutorial_example)
            help_tab.diploma_example_requested.connect(self._save_diploma_example)

        project_tab = self.tabs.get("project_tab")
        if project_tab is not None:
            for widget in (
                project_tab.edit_name, project_tab.edit_customer,
                project_tab.edit_alloy,
            ):
                widget.textEdited.connect(
                    lambda *_args: (
                        self._update_project_title(),
                        self._schedule_autosave()))
            project_tab.help_requested.connect(
                lambda: self._select_section(
                    next(i for i, (_, key) in enumerate(self.SECTIONS)
                         if key == "help_tab")))
            project_tab.project_changed.connect(
                lambda *_args: self._recalculate_dependents(with_time_funds=True))

        funds_tab = self.tabs.get("time_funds_tab")
        if funds_tab is not None:
            funds_tab.funds_updated.connect(
                lambda *_args: self._recalculate_dependents())

        for key in (
            "melting_tab", "molding_tab", "core_tab", "sand_tab",
            "cleaning_tab", "warehouse_tab", "transport_tab",
        ):
            signal = self._choice_signal(self.tabs.get(key))
            if signal is not None:
                signal.connect(
                    lambda *_args: self._recalculate_dependents())
        for key, signal_name in (
            ("workforce_tab", "workforce_changed"),
            ("areas_tab", "areas_recalculated"),
        ):
            tab = self.tabs.get(key)
            signal = getattr(tab, signal_name, None)
            if signal is not None:
                signal.connect(lambda *_args: self._recalculate_dependents())

    def showEvent(self, event) -> None:  # noqa: N802
        """Show first-run offer only after the real application is visible."""
        super().showEvent(event)
        if not self._startup_offer_checked:
            self._startup_offer_checked = True
            QTimer.singleShot(0, self._first_show_recovery_or_tutorial)

    def _schedule_autosave(self) -> None:
        """Debounce edits; periodic 60s timer catches changes without signals."""
        if not self._autosave_periodic.isActive():
            return
        self._autosave_debounce.start()

    def _capture_all_equipment_choices(self) -> dict:
        choices = UserChoices()
        old = choices.get_project_choices(self._choice_origin_project_id)
        current = choices.get_project_choices(self.project.project_id)
        def merge(previous, recent):
            if not isinstance(previous, dict) or not isinstance(recent, dict):
                return recent
            combined = dict(previous)
            for key, value in recent.items():
                combined[key] = (merge(combined[key], value)
                                 if key in combined else value)
            return combined
        return merge(old, current)

    def _autosave_snapshot(self) -> None:
        """Never touch the original project file. Failures are non-modal."""
        self._autosave_debounce.stop()
        if not self._autosave_ready:
            return
        try:
            self._flush_pending_text_inputs()
            signature = self._project_signature()
            if signature == self._saved_signature:
                return
            if (self._autosave_last_signature == signature
                    and self._recovery_store.path_for(self._recovery_id).exists()):
                return
            # A corrupt optional catalogue must not prevent the actual
            # castings/project from being rescued.
            try:
                catalogs = read_custom_catalogs(USER_DATA_DIR)
            except (OSError, ValueError):
                catalogs = {}
            self._recovery_store.save_snapshot(
                self._recovery_id,
                self.project,
                self._capture_all_equipment_choices(),
                catalogs,
                self._project_path,
            )
            self._autosave_last_signature = signature
            self.statusBar().showMessage(
                "Резервная копия несохранённой работы обновлена", 5000)
        except (OSError, ValueError, TypeError) as exc:
            self.statusBar().showMessage(
                f"Резервное автосохранение не выполнено: {exc}", 10000)

    def _remove_active_recovery(self) -> None:
        """Only called after user saves, discards or explicitly closes."""
        try:
            self._recovery_store.delete_snapshot(self._recovery_id)
        except OSError:
            pass
        self._autosave_last_signature = None

    def _show_version_history(self, _checked=False) -> None:
        """Browse prior saved versions for the currently opened file."""
        source = self._project_path
        if source is None:
            QMessageBox.information(
                self, "История версий",
                "Сначала сохраните проект в файл через «Сохранить как…».")
            return
        try:
            entries = self._version_history.list_versions(source)
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.warning(self, "История версий", str(exc))
            return
        if not entries:
            QMessageBox.information(
                self, "История версий",
                "Предыдущих версий пока нет. Версия создаётся перед "
                "повторным сохранением файла.")
            return
        previous = getattr(self, "_version_history_dialog", None)
        if previous is not None and previous.isVisible():
            previous.raise_()
            return
        dialog = VersionHistoryDialog(entries, self)
        self._version_history_dialog = dialog
        dialog.finished.connect(
            lambda _result, dlg=dialog: self._version_history_finished(dlg))
        dialog.open()

    def _version_history_finished(self, dialog: VersionHistoryDialog) -> None:
        entry = dialog.selected_entry
        if entry is None:
            return
        # The picker is modeless: the active project could have changed.
        if (self._project_path is None
                or self._project_path.resolve() != entry.source_path):
            QMessageBox.warning(
                self, "История версий",
                "Проект изменился. Откройте историю версий ещё раз.")
            return
        if self._confirm_discard_project():
            self._restore_version_entry(entry)

    def _first_show_recovery_or_tutorial(self) -> None:
        # The recovery prompt has higher priority than the first-use tour.
        if not self._show_recovery_dialog(startup=True):
            self._offer_tutorial_once()

    def _show_recovery_dialog(
        self, _checked=False, *, startup: bool = False
    ) -> bool:
        app = QApplication.instance()
        if startup and app is not None and app.platformName() == "offscreen":
            return False
        entries = self._recovery_store.list_snapshots()
        if not entries:
            if not startup:
                QMessageBox.information(
                    self, "Восстановление",
                    "Несохранённых аварийных копий не найдено.")
            return False
        existing = getattr(self, "_recovery_dialog", None)
        if existing is not None and existing.isVisible():
            existing.raise_()
            return True
        dialog = RecoveryDialog(entries, self)
        self._recovery_dialog = dialog
        dialog.finished.connect(
            lambda _result, dlg=dialog, initial=startup:
                self._recovery_dialog_finished(dlg, initial))
        dialog.open()
        return True

    def _recovery_dialog_finished(
        self, dialog: RecoveryDialog, startup: bool
    ) -> None:
        entry = dialog.selected_entry
        deletion = dialog.delete_entry
        if deletion is not None:
            try:
                self._recovery_store.delete_snapshot(deletion.snapshot_id)
            except OSError as exc:
                QMessageBox.warning(self, "Резервная копия", str(exc))
        elif entry is not None and self._confirm_discard_project():
            self._restore_recovery_entry(entry)
        # "Позже" keeps ALL snapshots on disk for next launch or menu action.
        if startup:
            self._offer_tutorial_once()

    def _restore_recovery_entry(self, entry: RecoveryEntry) -> bool:
        """User opt-in; source file is untouched until explicit Ctrl+S."""
        try:
            loaded, original, original_changed = (
                self._recovery_store.load_snapshot(entry))
            project = loaded.project
            if not project.project_uid:
                project.project_uid = uuid4().hex
            pending = plan_custom_catalog_restore(
                USER_DATA_DIR, loaded.custom_catalogs)
            restore_custom_catalogs(pending)
            UserChoices().replace_project_choices(
                project.project_id, loaded.choices)
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.critical(
                self, "Восстановление не выполнено",
                f"Открытый проект сохранён без изменений.\n\n{exc}")
            return False
        self._activate_project(
            project, original, recovery_id=entry.snapshot_id)
        # Snapshot represents UNSAVED work even if the original is attached.
        self._saved_signature = ""
        self._update_project_title()
        self._schedule_autosave()
        if original_changed:
            QMessageBox.warning(
                self, "Исходный файл изменился",
                "Основной файл был изменён или перемещён после создания "
                "резервной копии. Восстановленная работа открыта отдельно. "
                "Используйте «Сохранить как…», чтобы не затереть другую версию.")
        return True

    def _offer_tutorial_once(self) -> None:
        if not self._onboarding.should_offer():
            return
        # Mark BEFORE showing: cancelling, closing or starting the tour
        # must never trigger the automated invitation again.
        try:
            self._onboarding.mark_offered()
        except OSError:
            # Do not prevent the user from using the program if the profile is
            # temporarily read-only. Suppression still holds in this session.
            pass
        prompt = QMessageBox(self)
        prompt.setWindowTitle("Добро пожаловать в ЛитейныйЦех PRO")
        prompt.setIcon(QMessageBox.Information)
        prompt.setText("В программе есть пошаговое обучение для новых пользователей.")
        prompt.setInformativeText(
            "Экскурсия покажет, что вводить в каждой вкладке, "
            "как открыть учебный Excel и где смотреть ошибки расчёта. "
            "Она не изменяет ваш проект.\n\n"
            "Это предложение показывается только при первом запуске. "
            "Позже обучение можно открыть вручную в разделе «❓ Руководство».")
        start_button = prompt.addButton("Начать обучение", QMessageBox.AcceptRole)
        prompt.addButton("Не сейчас", QMessageBox.RejectRole)
        prompt.setDefaultButton(start_button)
        prompt.finished.connect(
            lambda _result: self.start_tutorial()
            if prompt.clickedButton() is start_button else None)
        self._welcome_prompt = prompt
        prompt.open()

    def start_tutorial(self) -> None:
        """Guided in-app navigation; it never edits the active Project."""
        if self._tour_index >= 0:
            self._tour_index = 0
        else:
            self._tour_origin = self.content_stack.currentIndex()
            self._tour_index = 0
        self.tour_banner.show()
        self._show_tutorial_step()

    def _show_tutorial_step(self) -> None:
        if self._tour_index < 0:
            return
        step = TUTORIAL_STEPS[self._tour_index]
        self.tour_heading.setText(
            f"Шаг {self._tour_index + 1} из {len(TUTORIAL_STEPS)} — {step.title}")
        self.tour_instruction.setText(step.instruction)
        self.tour_back_button.setEnabled(self._tour_index > 0)
        self.tour_example_button.setVisible(step.title == "Номенклатура отливок")
        self.tour_next_button.setText(
            "Завершить" if self._tour_index == len(TUTORIAL_STEPS) - 1
            else "Далее →")
        idx = next((i for i, (_, key) in enumerate(self.SECTIONS)
                    if key == step.section), None)
        if idx is not None:
            self._select_section(idx)
            tab = self.tabs[step.section]
            widget = getattr(tab, step.focus_name, None) if step.focus_name else None
            if isinstance(widget, QWidget):
                for scroll in tab.findChildren(QScrollArea):
                    body = scroll.widget()
                    if body and (body is widget or body.isAncestorOf(widget)):
                        scroll.ensureWidgetVisible(widget, 15, 15)
                        break
                widget.setFocus(Qt.OtherFocusReason)

    def _tour_back(self) -> None:
        if self._tour_index > 0:
            self._tour_index -= 1
            self._show_tutorial_step()

    def _tour_next(self) -> None:
        if self._tour_index < 0:
            return
        if self._tour_index == len(TUTORIAL_STEPS) - 1:
            self._stop_tutorial()
        else:
            self._tour_index += 1
            self._show_tutorial_step()

    def _stop_tutorial(self) -> None:
        if self._tour_index < 0:
            return
        self._tour_index = -1
        self.tour_banner.hide()
        self._select_section(self._tour_origin)

    def _save_tutorial_example(self) -> None:
        proposed = str(Path.home() / "ЛитейныйЦех_учебный_пример.xlsx")
        filename, _ = QFileDialog.getSaveFileName(
            self, "Сохранить учебный Excel", proposed, "Excel (*.xlsx)",
            options=QFileDialog.DontUseNativeDialog)
        if not filename:
            return
        try:
            saved = save_tutorial_excel(Path(filename))
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Ошибка сохранения примера", str(exc))
            return
        QMessageBox.information(
            self, "Учебный Excel сохранён",
            f"Файл создан:\n{saved}\n\nОн НЕ был загружен в текущий проект. "
            "Чтобы изучить импорт, откройте «Исходные данные» → "
            "«Импорт из Excel». Это заменит текущую номенклатуру.")

    def _save_diploma_example(self, number: int) -> None:
        """Save an unmodified verified diploma workbook, never import it."""
        if number not in (1, 2):
            return
        source = EXAMPLES_DIR / f"Диплом_{number}_ведомость_формовки.xlsx"
        if not source.is_file():
            QMessageBox.critical(
                self, "Файл примера отсутствует",
                f"Контрольная ведомость не включена в комплект:\n{source}")
            return
        target, _ = QFileDialog.getSaveFileName(
            self, "Сохранить исходную дипломную ведомость",
            str(Path.home() / source.name), "Excel (*.xlsx)",
            options=QFileDialog.DontUseNativeDialog)
        if not target:
            return
        destination = Path(target)
        if destination.suffix.lower() != ".xlsx":
            destination = destination.with_suffix(".xlsx")
        if destination.exists():
            answer = QMessageBox.question(
                self, "Файл существует",
                f"Заменить файл {destination.name}?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
        try:
            if destination.resolve() != source.resolve():
                copyfile(source, destination)
        except OSError as exc:
            QMessageBox.critical(
                self, "Не удалось сохранить дипломный Excel", str(exc))
            return
        QMessageBox.information(
            self, "Дипломный Excel сохранён",
            f"Сохранён файл:\n{destination}\n\nВнутри — исходные строки "
            "диплома, таблица импорта A–P и лист сверки. "
            "Текущий проект НЕ изменён. Для проверки воспользуйтесь "
            "кнопкой «Импорт из Excel» в исходных данных.")

    def department_summaries(self) -> dict:
        """Собрать сводки (`get_summary`) всех реализованных отделений.

        Returns:
            Словарь ``{melting, molding, cores, sand_prep, cleaning,
            warehouses, workforce}`` — пустые словари там, где вкладка
            ещё не реализована или данные не готовы
        """
        def summary(key: str) -> dict:
            tab = self.tabs.get(key)
            fn = getattr(tab, "get_summary", None)
            if callable(fn):
                try:
                    return fn() or {}
                except Exception:
                    return {}
            return {}

        return {
            "melting": summary("melting_tab"),
            "molding": summary("molding_tab"),
            "cores": summary("core_tab"),
            "sand_prep": summary("sand_tab"),
            "cleaning": summary("cleaning_tab"),
            "warehouses": summary("warehouse_tab"),
            "workforce": summary("workforce_tab"),
            "areas": summary("areas_tab"),
            "transport": summary("transport_tab"),
        }

    def _select_section(self, index: int) -> None:
        if not (0 <= index < len(self.nav_buttons)):
            return
        for i, btn in enumerate(self.nav_buttons):
            btn.setChecked(i == index)
        self.content_stack.setCurrentIndex(index)

    def _on_project_changed(self) -> None:
        """Реактивный пересчёт при изменении исходных данных."""
        print(f"[MainWindow] Проект изменён: {self.project.name}, "
              f"выпуск={self.project.annual_output_t} т/год, "
              f"позиций={self.project.total_castings_count()}")

    def _apply_theme(self) -> None:
        """Единая палитра для окна, диалогов, выпадающих списков и текстовых полей.

        Темы на отдельном MainWindow недостаточно: всплывающие QDialog и
        системные редакторы могут наследовать светлую палитру Windows.
        """
        app = QApplication.instance()
        if app is None:
            return
        app.setStyle("Fusion")
        palette = QPalette()
        for role, name in (
            (QPalette.Window, "bg_main"),
            (QPalette.WindowText, "text_primary"),
            (QPalette.Base, "bg_input"),
            (QPalette.AlternateBase, "bg_panel"),
            (QPalette.Text, "text_primary"),
            (QPalette.Button, "bg_panel"),
            (QPalette.ButtonText, "text_primary"),
            (QPalette.ToolTipBase, "bg_panel"),
            (QPalette.ToolTipText, "text_primary"),
            (QPalette.Highlight, "separator"),
            (QPalette.HighlightedText, "text_primary"),
            (QPalette.PlaceholderText, "text_secondary"),
        ):
            palette.setColor(role, QColor(COLORS[name]))
        app.setPalette(palette)
        if THEME_QSS.is_file():
            app.setStyleSheet(THEME_QSS.read_text(encoding="utf-8"))
