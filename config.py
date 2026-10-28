"""Конфигурация приложения «ЛитейныйЦех PRO»."""
from pathlib import Path
import os
import sys

APP_NAME = "ЛитейныйЦех PRO"
APP_VERSION = "0.3.0-stage3"
APP_AUTHOR = "Foundry Engineering Team"

# Корневая директория проекта
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
ASSETS_DIR = BASE_DIR / "assets"
STYLES_DIR = ASSETS_DIR / "styles"
ICONS_DIR = ASSETS_DIR / "icons"

# Упакованные справочники читаются из каталога PyInstaller; настройки
# пользователя ВСЕГДА в доступном для записи профиле Windows.
if getattr(sys, "frozen", False):
    USER_DATA_DIR = Path(os.environ.get("APPDATA") or
                         (Path.home() / "AppData" / "Roaming")) / "LiteynyiTsehPRO"
else:
    USER_DATA_DIR = BASE_DIR / "user_data"

# Тема
THEME_QSS = STYLES_DIR / "dark_theme.qss"
APP_ICON = ICONS_DIR / "app_icon.ico"

# Цветовая палитра (утверждена)
COLORS = {
    "bg_main":       "#2D0A0A",   # глубокий бордо
    "bg_panel":      "#4A1515",   # тёмно-винный
    "text_primary":  "#F4D03F",   # тёплое золото
    "text_secondary":"#C9A84C",   # приглушённое золото
    "accent":        "#FF6B35",   # огненный оранжевый
    "separator":     "#B87333",   # медный
    "success":       "#4CAF50",   # зелёный (нормальная загрузка)
    "warning":       "#FFC107",   # янтарный (загрузка вне оптимума)
}

# Режимы работы цеха (по умолчанию — как в дипломе)
DEFAULT_MODE = {
    "shifts_per_day": 2,          # 2 смены
    "shift_duration_h": 8,        # 8 часов
    "working_days_per_year": 249, # 249 рабочих дней (из диплома)
    "weekends_per_year": 104,
    "holidays_per_year": 12,
}

# Базовые коэффициенты (по методичке/диплому)
DEFAULT_COEFFICIENTS = {
    "K_brak": 0.05,               # 5% брак
    "K_ugar_steel": 0.05,         # 5% угар для стали
    "K_litniki_i_pribyli": 0.289, # 28.9% литники и прибыли (из диплома)
    "K_neravnomernosti": 1.0,     # коэффициент неравномерности
}