"""Read-only, searchable built-in technical references with primary sources."""
from __future__ import annotations

from html import escape

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QTabWidget, QTextBrowser,
    QLineEdit, QPushButton,
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
            "Встроенные марки по ГОСТ и параметры машин из каталогов изготовителей. "
            "Проверено происхождение указанных сведений, НЕ пригодность для конкретного "
            "проекта. Значения без источника и условия применения не выводятся как нормативные."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск марки, модели, ГОСТ или параметра…")
        layout.addWidget(self.search)
        self.tabs = QTabWidget()
        self.records = list_official_references()
        self._browsers = {}
        for category, rows in self.records.items():
            browser = QTextBrowser()
            browser.setOpenExternalLinks(True)
            browser.setReadOnly(True)
            browser.setStyleSheet(
                "QTextBrowser { background: #202b3b; color: #ecf2f9; "
                "border: 1px solid #405067; padding: 12px; }"
            )
            self._browsers[category] = browser
            self.tabs.addTab(browser, f"{category} ({len(rows)})")
        self.search.textChanged.connect(self._refresh_tables)
        self._refresh_tables()
        layout.addWidget(self.tabs, 1)
        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

    @staticmethod
    def _source_cell(rec: dict) -> str:
        primary = (
            "<a href=\"" + escape(rec["url"], quote=True) +
            "\">Официальный реестр / производитель</a>"
        )
        reproduced = rec.get("text_url")
        if reproduced:
            primary += (
                "<p><a href=\"" + escape(reproduced, quote=True) +
                "\">Текст пункта ГОСТ (сторонняя публикация)</a></p>"
            )
        return escape(rec["source"]) + "<p>" + primary + "</p>"

    def _refresh_tables(self, _text=None) -> None:
        query = self.search.text().strip().casefold()
        for idx, (category, records) in enumerate(self.records.items()):
            matches = [
                rec for rec in records
                if not query or any(
                    query in str(rec.get(key, "")).casefold()
                    for key in ("name", "specs", "source", "conditions")
                )
            ]
            rows = []
            for rec in matches:
                rows.append(
                    "<tr><td><b>" + escape(rec["name"]) + "</b></td>"
                    "<td>" + escape(rec["specs"]) + "</td>"
                    "<td>" + escape(rec["conditions"]) + "</td>"
                    "<td>" + self._source_cell(rec) + "</td></tr>"
                )
            html = (
                "<html><body style='color:#edf2f8'>"
                "<table border='1' cellspacing='0' cellpadding='8' "
                "style='border-color:#60738c'>"
                "<tr><th>Модель / марка</th><th>Опубликованные характеристики</th>"
                "<th>Условия и ограничения</th><th>Источники</th></tr>"
                + "".join(rows) + "</table></body></html>"
            )
            browser = self._browsers[category]
            browser.setHtml(html)
            self.tabs.setTabText(idx, f"{category} ({len(matches)}/{len(records)})")
