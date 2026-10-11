"""Главное окно приложения с боковой навигацией."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QStackedWidget, QPushButton, QLabel, QFrame,
)

from config import APP_NAME, APP_VERSION, COLORS, THEME_QSS
from core.project import Project

# Импорты реальных вкладок
from gui.tabs.project_tab import ProjectTab
from gui.tabs.time_funds_tab import TimeFundsTab
from gui.tabs.melting_tab import MeltingTab
from gui.tabs.molding_tab import MoldingTab
from gui.tabs.core_tab import CoreTab


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
                background-color: #5A1F1F;
                border-left: 3px solid {COLORS['accent']};
            }}
            QPushButton:checked {{
                background-color: #6B2525;
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
        ("📊 Сводка",             "summary_tab"),
    ]

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.setMinimumSize(1280, 800)
        self.resize(1440, 900)

        # Модель проекта (единая для всех вкладок)
        self.project = Project()

        self._apply_theme()
        self._build_ui()
        self._connect_signals()
        self._select_section(0)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ── Боковая панель ──
        self.sidebar = QFrame()
        self.sidebar.setFixedWidth(260)
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
        root_layout.addWidget(self.content_stack, 1)

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

    def _connect_signals(self) -> None:
        """Связать сигналы между вкладками для реактивности."""
        project_tab = self.tabs.get("project_tab")
        time_funds_tab = self.tabs.get("time_funds_tab")
        melting_tab = self.tabs.get("melting_tab")
        molding_tab = self.tabs.get("molding_tab")
        core_tab = self.tabs.get("core_tab")

        if project_tab and time_funds_tab:
            # При изменении исходных данных → пересчёт фондов времени
            project_tab.project_changed.connect(time_funds_tab.on_project_changed)

        if project_tab and melting_tab:
            # При изменении исходных данных → пересчёт завалки и подбор печей
            project_tab.project_changed.connect(melting_tab.on_project_changed)

        if project_tab and molding_tab:
            # При изменении исходных данных → пересчёт программы формовки
            project_tab.project_changed.connect(molding_tab.on_project_changed)

        if time_funds_tab and melting_tab:
            # Фонд времени оборудования влияет на подбор печей и линий
            time_funds_tab.funds_updated.connect(melting_tab.on_project_changed)

        if time_funds_tab and molding_tab:
            time_funds_tab.funds_updated.connect(molding_tab.on_project_changed)

        if project_tab and core_tab:
            # При изменении исходных данных → пересчёт программы стержней
            project_tab.project_changed.connect(core_tab.on_project_changed)

        if time_funds_tab and core_tab:
            time_funds_tab.funds_updated.connect(core_tab.on_project_changed)

        if molding_tab and core_tab:
            # Смена линии/программы формовки влияет на загрузку стержневых машин
            molding_tab.line_choice_changed.connect(
                lambda _equipment: core_tab.refresh())

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
        if THEME_QSS.exists():
            with open(THEME_QSS, "r", encoding="utf-8") as f:
                self.setStyleSheet(f.read())
        else:
            self.setStyleSheet(f"""
                QMainWindow {{ background-color: {COLORS['bg_main']}; }}
                QLabel {{ color: {COLORS['text_primary']}; }}
            """)