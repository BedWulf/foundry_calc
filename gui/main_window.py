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
from gui.tabs.sand_tab import SandTab
from gui.tabs.cleaning_tab import CleaningTab
from gui.tabs.warehouse_tab import WarehouseTab
from gui.tabs.workforce_tab import WorkforceTab
from gui.tabs.areas_tab import AreasTab
from gui.tabs.transport_tab import TransportTab


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
        ("🚛 Транспорт",          "transport_tab"),
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

    def _connect_signals(self) -> None:
        """Связать сигналы между вкладками для реактивности."""
        project_tab = self.tabs.get("project_tab")
        time_funds_tab = self.tabs.get("time_funds_tab")
        melting_tab = self.tabs.get("melting_tab")
        molding_tab = self.tabs.get("molding_tab")
        core_tab = self.tabs.get("core_tab")
        sand_tab = self.tabs.get("sand_tab")
        cleaning_tab = self.tabs.get("cleaning_tab")

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

        if project_tab and sand_tab:
            # При изменении исходных данных → пересчёт расхода смеси и парка
            project_tab.project_changed.connect(sand_tab.on_project_changed)

        if time_funds_tab and sand_tab:
            # Фонд времени оборудования влияет на число смесителей
            time_funds_tab.funds_updated.connect(sand_tab.on_project_changed)

        if molding_tab and sand_tab:
            # Смена программы/линии формовки меняет число и объём форм →
            # годовой расход формовочной смеси
            molding_tab.line_choice_changed.connect(
                lambda _equipment: sand_tab.refresh())

        if project_tab and cleaning_tab:
            # При изменении исходных данных → пересчёт тоннажей и парка очистки
            project_tab.project_changed.connect(cleaning_tab.on_project_changed)

        if time_funds_tab and cleaning_tab:
            # Фонд времени оборудования влияет на число очистных установок
            time_funds_tab.funds_updated.connect(cleaning_tab.on_project_changed)

        if molding_tab and cleaning_tab:
            # Смена программы/линии формовки меняет число форм → тоннаж выбивки
            molding_tab.line_choice_changed.connect(
                lambda _equipment: cleaning_tab.refresh())

        warehouse_tab = self.tabs.get("warehouse_tab")
        workforce_tab = self.tabs.get("workforce_tab")
        areas_tab = self.tabs.get("areas_tab")
        transport_tab = self.tabs.get("transport_tab")

        if project_tab and warehouse_tab:
            # При изменении исходных данных → пересчёт нормативов складов
            project_tab.project_changed.connect(warehouse_tab.on_project_changed)

        if project_tab and workforce_tab:
            # При изменении исходных данных → пересчёт ведомости РБ
            project_tab.project_changed.connect(workforce_tab.on_project_changed)

        # Реактивная связка «отделения → рабочая сила»: любое изменение
        # выбора оборудования или программы пересчитывает численность
        for tab in (melting_tab, molding_tab, core_tab, sand_tab, cleaning_tab):
            sig = self._choice_signal(tab)
            if tab is not None and sig is not None and workforce_tab is not None:
                sig.connect(lambda _data: workforce_tab.refresh())

        if workforce_tab is not None:
            # Численность цеха нужна для склада инструмента; провайдер
            # собирает сводки всех отделений одним вызовом
            workforce_tab.set_dependencies_provider(self.department_summaries)

        if warehouse_tab is not None and workforce_tab is not None:
            # После пересчёта РБ склады уточняют площадь инструментария
            workforce_tab.workforce_changed.connect(
                lambda _data: warehouse_tab.refresh())

        # Связки «отделения → склады»: запасы шихты зависят от
        # металлозавалки, склады материалов — от тоннажей смесей
        for tab in (melting_tab, molding_tab, core_tab, sand_tab):
            sig = self._choice_signal(tab)
            if tab is not None and sig is not None and warehouse_tab is not None:
                sig.connect(lambda _data: warehouse_tab.refresh())

        # ── Вкладка «Площади»: финальная ведомость по всем отделениям ──
        if areas_tab is not None:
            if project_tab is not None:
                project_tab.project_changed.connect(areas_tab.on_project_changed)
            if time_funds_tab is not None:
                time_funds_tab.funds_updated.connect(areas_tab.on_project_changed)
            # Любая смена выбора оборудования в любом отделении (и складах)
            # меняет габаритную площадь → пересчёт ведомости площадей
            for tab in (melting_tab, molding_tab, core_tab, sand_tab,
                        cleaning_tab, warehouse_tab, workforce_tab):
                sig = self._choice_signal(tab)
                if tab is not None and sig is not None:
                    sig.connect(lambda _data: areas_tab.refresh())

        # ── Вкладка «Транспорт»: зависит от жидкого металла и площадей ──
        if transport_tab is not None:
            if project_tab is not None:
                project_tab.project_changed.connect(
                    transport_tab.on_project_changed)
            if melting_tab is not None:
                # Металлозавалка/жидкий металл задают парк ковшей;
                # выбор печей влияет на заливочное хозяйство
                self._choice_signal(melting_tab).connect(
                    lambda _data: transport_tab.refresh())
            if areas_tab is not None:
                # Ведомость площадей даёт фактические длины участков
                # для норм кранов → пересчёт при смене парка оборудования
                areas_tab.areas_recalculated.connect(
                    lambda _data: transport_tab.refresh())

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
        if THEME_QSS.exists():
            with open(THEME_QSS, "r", encoding="utf-8") as f:
                self.setStyleSheet(f.read())
        else:
            self.setStyleSheet(f"""
                QMainWindow {{ background-color: {COLORS['bg_main']}; }}
                QLabel {{ color: {COLORS['text_primary']}; }}
            """)