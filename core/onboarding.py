"""Первый запуск: предложение пройти экскурсию ровно один раз для данного профиля."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from config import USER_DATA_DIR


class OnboardingState:
    """Состояние предложения обучения, НЕ зависящее от имени проекта.

    Флаг записывается до отображения окна, поэтому даже закрытие приложения
    во время предложения не приведёт к повторному автоматическому показу.
    """

    def __init__(self, root: Path | None = None):
        self.path = Path(root) / "onboarding.json" if root else USER_DATA_DIR / "onboarding.json"

    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (FileNotFoundError, OSError, ValueError):
            return {}

    def should_offer(self) -> bool:
        return not bool(self._read().get("tutorial_offered"))

    def mark_offered(self) -> None:
        data = self._read()
        data["tutorial_offered"] = True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)


from dataclasses import dataclass


@dataclass(frozen=True)
class TutorialStep:
    section: str
    title: str
    instruction: str
    focus_name: str = ""


TUTORIAL_STEPS: tuple[TutorialStep, ...] = (
    TutorialStep(
        "help_tab", "Добро пожаловать",
        "Это интерактивная экскурсия по настоящим разделам программы. "
        "Мы покажем маршрут расчёта, объясним поля и создадим учебный Excel. "
        "Экскурсия не меняет ваш проект; значения вводятся только вами."),
    TutorialStep(
        "project_tab", "Исходные данные проекта",
        "Укажите название, сплав, годный выпуск в т/год, график смен и потери. "
        "Годной продукции в тоннах нельзя подменять штуками. "
        "Для учебного примера не нужно менять рабочий проект.",
        "spin_annual"),
    TutorialStep(
        "project_tab", "Номенклатура отливок",
        "Используйте «Сохранить учебный Excel» в разделе «Руководство». "
        "На реальном проекте нажмите «Импорт из Excel», затем проверьте "
        "форм/год, опоки и кг заливаемого металла на ОДНУ форму. "
        "Импорт ЗАМЕНЯЕТ текущую номенклатуру.",
        "btn_import"),
    TutorialStep(
        "time_funds_tab", "Фонды времени",
        "Проверьте действительный фонд оборудования в ч/год. "
        "Количество смен и часов задаётся в исходных данных; фонд "
        "оборудования не равен фонду рабочего."),
    TutorialStep(
        "molding_tab", "Общие формовочные линии",
        "Разные отливки допускается выпускать последовательно партиями "
        "на одной совместимой линии. Выберите автоподбор или ручной парк; "
        "задайте переналадки, число линий и максимальную загрузку. "
        "Красный дефицит форм означает, что программа не выполняется.",
        "_park_mode"),
    TutorialStep(
        "melting_tab", "Соседние отделения",
        "Проверьте плавку, стержни, смесеприготовление, очистку и склады. "
        "Обращайте внимание на единицы: т/год, м³/год, стержней/год. "
        "Неизвестные паспорта оборудования — не подтверждённая мощность."),
    TutorialStep(
        "areas_tab", "Персонал, площади, транспорт",
        "При изменении количества линий изменяются их парк, площадь и "
        "оценка персонала. Проверьте транспорт ковшей и кранов: годовой "
        "баланс не гарантирует работу в каждой смене."),
    TutorialStep(
        "summary_tab", "Сводка и предупреждения",
        "Откройте «Баланс мощностей и узкие места» и «Сменный сценарий». "
        "Статусы «ДЕФИЦИТ» и «Не проверено» требуют внимания. "
        "Экспорт Excel — предварительная инженерная модель, а не готовый "
        "промышленный проект."),
    TutorialStep(
        "help_tab", "Обучение завершено",
        "Вы знаете маршрут работы. Полная инструкция остаётся в «❓ Руководство». "
        "Нажмите «Завершить», чтобы вернуться к предыдущей вкладке. "
        "Экскурсию можно повторить вручную в любое время."),
)
