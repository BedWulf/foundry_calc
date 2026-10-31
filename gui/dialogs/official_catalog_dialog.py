"""Read-only built-in source-backed foundry equipment reference viewer."""
from __future__ import annotations

from html import escape

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QTabWidget, QTextBrowser, QPushButton
)

from core.official_reference_catalog import list_official_references


class OfficialCatalogDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Официальные технические справочники")
        self.resize(1180, 760)
        self.setMinimumSize(850, 560)
        layout = QVBoxLayout(self)
        note = QLabel(
            "Встроенные справочники изготовителей и ГОСТ. "
            "Подтверждена публикация указанных значений, но НЕ пригодность "
            "оборудования для конкретного проекта. Данные не экстраполируются."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        tabs = QTabWidget()
        self.records = list_official_references()
        for category, records in self.records.items():
            browser = QTextBrowser()
            browser.setOpenExternalLinks(True)
            browser.setReadOnly(True)
            browser.setStyleSheet(
                "QTextBrowser { background: #202b3b; color: #ecf2f9; "
                "border: 1px solid #405067; padding: 12px; }"
            )
            items = []
            for rec in records:
                items.append(
                    "<tr><td><b>" + escape(rec["name"]) + "</b></td>"
                    "<td>" + escape(rec["specs"]) + "</td>"
                    "<td>" + escape(rec["conditions"]) + "</td>"
                    "<td><a href=\"" + escape(rec["url"], quote=True) +
                    "\">" + escape(rec["source"]) + "</a></td></tr>"
                )
            html = (
                "<html><body style='color:#edf2f8'>"
                "<table border='1' cellspacing='0' cellpadding='8' "
                "style='border-color:#60738c'>"
                "<tr><th>Модель / марка</th><th>Опубликованные характеристики</th>"
                "<th>Условия и ограничения</th><th>Документ изготовителя / ГОСТ</th></tr>"
                + "".join(items) + "</table></body></html>"
            )
            browser.setHtml(html)
            tabs.addTab(browser, f"{category} ({len(records)})")
        layout.addWidget(tabs, 1)
        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)
