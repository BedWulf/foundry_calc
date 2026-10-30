"""Редактирование и подтверждение технологических данных одной отливки.

No source is invented and confirming a number requires a written reference
to the drawing, technical card or comparable primary project document.
"""
from dataclasses import replace

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QLabel, QLineEdit, QMessageBox, QSpinBox, QVBoxLayout,
)

from core.casting_item import CastingItem


class CastingTechnologyDialog(QDialog):
    """Edit a single row without rewriting other casting fields."""

    def __init__(self, casting: CastingItem, parent=None):
        super().__init__(parent)
        self.casting = casting
        self.result_item: CastingItem | None = None
        self.setWindowTitle(f"Проверка технологических данных — {casting.name}")
        self.setMinimumSize(650, 390)
        layout = QVBoxLayout(self)
        description = QLabel(
            "Подтверждение относится только к выбранной позиции. "
            "Укажите документ-источник каждого параметра. "
            "Неизвестную чистую массу оставьте равной 0 — это не означает "
            "физически нулевую массу.")
        description.setWordWrap(True)
        layout.addWidget(description)

        form = QFormLayout()
        self.cores_count = QSpinBox()
        self.cores_count.setRange(0, 100000)
        self.cores_count.setValue(casting.cores_count)
        self.cores_count.setSuffix(" шт/форму")
        self.cores_count_source = QLineEdit(casting.cores_count_source)
        self.cores_count_source.setPlaceholderText(
            "Чертёж, номер технологической карты или источник")
        self.cores_verified = QCheckBox("Число стержней сверено с источником")
        self.cores_verified.setChecked(casting.cores_count_verified)

        self.clean_mass = QDoubleSpinBox()
        self.clean_mass.setDecimals(3)
        self.clean_mass.setRange(0, 1_000_000_000)
        self.clean_mass.setSuffix(" кг/отливку")
        self.clean_mass.setValue(casting.mass_casting_kg)
        self.clean_mass_source = QLineEdit(casting.mass_casting_source)
        self.clean_mass_source.setPlaceholderText(
            "Чертёж, техкарта, ведомость массы")
        self.mass_verified = QCheckBox("Чистая масса сверена с источником")
        self.mass_verified.setChecked(casting.mass_casting_verified)

        form.addRow("Стержней в одной форме:", self.cores_count)
        form.addRow("Источник числа стержней:", self.cores_count_source)
        form.addRow("", self.cores_verified)
        form.addRow("Масса чистой отливки:", self.clean_mass)
        form.addRow("Источник чистой массы:", self.clean_mass_source)
        form.addRow("", self.mass_verified)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self) -> None:
        core_source = self.cores_count_source.text().strip()
        mass_source = self.clean_mass_source.text().strip()
        if self.cores_verified.isChecked() and not core_source:
            QMessageBox.warning(
                self, "Не указан источник",
                "Для подтверждения числа стержней укажите документ-источник.")
            return
        if self.mass_verified.isChecked() and (
            not mass_source or self.clean_mass.value() <= 0
        ):
            QMessageBox.warning(
                self, "Не подтверждена масса",
                "Для подтверждения чистой массы нужны положительная масса "
                "и документ-источник.")
            return
        if (self.clean_mass.value() > 0
                and self.casting.mass_with_LPS_kg > 0
                and self.clean_mass.value() > self.casting.mass_with_LPS_kg
                + max(0.01, self.casting.mass_with_LPS_kg * 0.001)):
            QMessageBox.warning(
                self, "Противоречие массы",
                "Чистая масса не может быть больше массы с ЛПС. "
                "Уточните исходные данные перед сохранением.")
            return

        self.result_item = replace(
            self.casting,
            cores_count=self.cores_count.value(),
            cores_count_source=core_source,
            cores_count_verified=self.cores_verified.isChecked(),
            mass_casting_kg=self.clean_mass.value(),
            mass_casting_source=mass_source,
            mass_casting_verified=self.mass_verified.isChecked(),
        )
        self.accept()
