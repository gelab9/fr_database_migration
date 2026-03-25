"""
Dashboard window — main entry point for the FR management application.

Displays a searchable, sortable table of all failure reports. Filters call
search_reports() in real time. Clicking a row emits report_selected(index)
so the detail/edit view can be opened by the parent application.
"""

from PyQt6.QtCore import (
    Qt,
    QSortFilterProxyModel,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QFont, QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QStatusBar,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from db.queries import fetch_all_reports, search_reports


# ---------------------------------------------------------------------------
# Column definitions
# ---------------------------------------------------------------------------

# (display header, dict key from query result)
COLUMNS = [
    ("New ID",             "New ID"),
    ("Project",            "Project"),
    ("Project #",          "Project_Number"),
    ("Meter Type",         "Meter_Type"),
    ("Serial Number",      "Meter_Serial_Number"),
    ("Test Type",          "Test_Type"),
    ("Date Failed",        "Date Failed"),
    ("Tested By",          "Tested By"),
    ("Assigned To",        "Assigned To"),
    ("Pass",               "Pass"),
    ("Anomaly",            "Anomaly"),
    ("FR Approved",        "FR_Approved"),
    ("Date Closed",        "Date Closed"),
]

HEADERS = [col[0] for col in COLUMNS]
KEYS    = [col[1] for col in COLUMNS]

# Column indices used for conditional row colouring
COL_APPROVED = KEYS.index("FR_Approved")
COL_PASS     = KEYS.index("Pass")

# Debounce delay (ms) before firing a search query after the user types
SEARCH_DEBOUNCE_MS = 300

# Approval filter dropdown options: (label, value passed to search_reports)
APPROVED_OPTIONS = [
    ("All",        None),
    ("Approved",   True),
    ("Unapproved", False),
]

TEST_TYPE_OPTIONS = [
    "All",
    "EMC",
    "Reliability",
    "Functional",
    "Environmental",
    "Accuracy",
    "Mechanical",
    "Safety",
    "Custom",
    "Past Tests",
]


# ---------------------------------------------------------------------------
# Table model
# ---------------------------------------------------------------------------

class ReportTableModel(QStandardItemModel):
    """Thin QStandardItemModel wrapper that stores the raw report dicts."""

    def __init__(self, parent=None):
        super().__init__(0, len(COLUMNS), parent)
        self.setHorizontalHeaderLabels(HEADERS)
        self._index_col: list[int] = []   # parallel list of [Index] values

    def load(self, reports: list[dict]):
        self.removeRows(0, self.rowCount())
        self._index_col.clear()

        for report in reports:
            row_items = []
            for key in KEYS:
                raw = report.get(key)
                text = "" if raw is None else str(raw)
                # Strip time component from date columns so they read cleanly
                if "Date" in key and " " in text:
                    text = text.split(" ")[0]
                item = QStandardItem(text)
                item.setEditable(False)
                row_items.append(item)

            # Row-level colour hints
            approved = report.get("FR_Approved", "")
            passed   = str(report.get("Pass", "")).strip().lower()
            if approved == "Unchecked":
                colour = QColor("#fff3cd")   # amber — pending review
            elif passed in ("no", "false", "0", "fail"):
                colour = QColor("#fde8e8")   # soft red — open failure
            else:
                colour = None

            if colour:
                for item in row_items:
                    item.setBackground(colour)

            self.appendRow(row_items)
            self._index_col.append(report.get("Index"))

    def index_for_row(self, row: int) -> int | None:
        """Return the [Index] PK for the given model row."""
        if 0 <= row < len(self._index_col):
            return self._index_col[row]
        return None


# ---------------------------------------------------------------------------
# Dashboard window
# ---------------------------------------------------------------------------

class DashboardWindow(QMainWindow):
    """
    Main application window.

    Signals
    -------
    report_selected : int
        Emitted with the [Index] value when the user double-clicks a row.
    """

    report_selected = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Failure Report Management System")
        self.resize(1400, 800)

        self._model = ReportTableModel(self)
        self._proxy = QSortFilterProxyModel(self)
        self._proxy.setSourceModel(self._model)
        self._proxy.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

        # Debounce timer so we don't query on every keystroke
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self._apply_filters)

        self._build_ui()
        self._load_all()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(8)
        root.setContentsMargins(12, 12, 12, 12)

        # ── Title bar ──────────────────────────────────────────────────
        title = QLabel("Failure Report Management System")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        root.addWidget(title)

        # ── Separator ──────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(sep)

        # ── Filter bar ─────────────────────────────────────────────────
        filter_bar = QHBoxLayout()
        filter_bar.setSpacing(10)

        # Search box
        filter_bar.addWidget(QLabel("Search:"))
        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText(
            "Search New ID, serial number, failure description, corrective action…"
        )
        self._search_box.setClearButtonEnabled(True)
        self._search_box.textChanged.connect(self._schedule_search)
        self._search_box.setMinimumWidth(320)
        filter_bar.addWidget(self._search_box, stretch=1)

        # Test Type dropdown
        filter_bar.addWidget(QLabel("Test Type:"))
        self._test_type_combo = QComboBox()
        self._test_type_combo.addItems(TEST_TYPE_OPTIONS)
        self._test_type_combo.setMinimumWidth(130)
        self._test_type_combo.currentIndexChanged.connect(self._schedule_search)
        filter_bar.addWidget(self._test_type_combo)

        # FR Approved dropdown
        filter_bar.addWidget(QLabel("Approved:"))
        self._approved_combo = QComboBox()
        for label, _ in APPROVED_OPTIONS:
            self._approved_combo.addItem(label)
        self._approved_combo.setMinimumWidth(110)
        self._approved_combo.currentIndexChanged.connect(self._schedule_search)
        filter_bar.addWidget(self._approved_combo)

        # Refresh button
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setFixedWidth(80)
        self._refresh_btn.clicked.connect(self._load_all)
        filter_bar.addWidget(self._refresh_btn)

        root.addLayout(filter_bar)

        # ── Table ──────────────────────────────────────────────────────
        self._table = QTableView()
        self._table.setModel(self._proxy)
        self._table.setSortingEnabled(True)
        self._table.setSelectionBehavior(
            QTableView.SelectionBehavior.SelectRows
        )
        self._table.setSelectionMode(
            QTableView.SelectionMode.SingleSelection
        )
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setHighlightSections(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        self._table.setShowGrid(True)
        self._table.setWordWrap(False)

        # Sensible default column widths
        default_widths = {
            "New ID": 70,
            "Project": 120,
            "Project #": 90,
            "Meter Type": 130,
            "Serial Number": 130,
            "Test Type": 100,
            "Date Failed": 95,
            "Tested By": 110,
            "Assigned To": 110,
            "Pass": 55,
            "Anomaly": 65,
            "FR Approved": 95,
            "Date Closed": 95,
        }
        for i, header in enumerate(HEADERS):
            if header in default_widths:
                self._table.setColumnWidth(i, default_widths[header])

        self._table.doubleClicked.connect(self._on_row_double_clicked)
        root.addWidget(self._table)

        # ── Status bar ─────────────────────────────────────────────────
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._status.showMessage("Loading…")

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_all(self):
        """Fetch every report (no filters) and populate the table."""
        self._status.showMessage("Loading all reports…")
        QApplication.processEvents()
        reports = fetch_all_reports()
        self._model.load(reports)
        self._proxy.sort(0, Qt.SortOrder.AscendingOrder)
        count = self._model.rowCount()
        self._status.showMessage(f"{count} report{'s' if count != 1 else ''} loaded.")

    def _schedule_search(self):
        """Restart the debounce timer on every filter change."""
        self._debounce.start(SEARCH_DEBOUNCE_MS)

    def _apply_filters(self):
        """Build filter kwargs and call search_reports()."""
        search_text = self._search_box.text().strip()
        test_type_label = self._test_type_combo.currentText()
        approved_idx = self._approved_combo.currentIndex()

        test_type = "" if test_type_label == "All" else test_type_label
        _, approved_val = APPROVED_OPTIONS[approved_idx]

        self._status.showMessage("Searching…")
        QApplication.processEvents()

        reports = search_reports(
            search_text=search_text,
            test_type=test_type,
            approved=approved_val,
        )
        self._model.load(reports)
        self._proxy.sort(
            self._table.horizontalHeader().sortIndicatorSection(),
            self._table.horizontalHeader().sortIndicatorOrder(),
        )
        count = self._model.rowCount()
        self._status.showMessage(
            f"{count} report{'s' if count != 1 else ''} matched."
        )

    # ------------------------------------------------------------------
    # Row selection
    # ------------------------------------------------------------------

    def _on_row_double_clicked(self, proxy_index):
        """Map the proxy row back to the source model to get [Index]."""
        source_index = self._proxy.mapToSource(proxy_index)
        db_index = self._model.index_for_row(source_index.row())
        if db_index is not None:
            self.report_selected.emit(db_index)


# ---------------------------------------------------------------------------
# Standalone entry point (dev / testing)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    from pathlib import Path
    # Ensure the project root is on sys.path when this file is run directly
    # (i.e. `python ui/dashboard.py`).  Running via main.py is preferred.
    _project_root = Path(__file__).resolve().parent.parent
    if str(_project_root) not in sys.path:
        sys.path.insert(0, str(_project_root))

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = DashboardWindow()
    win.report_selected.connect(
        lambda idx: print(f"Report selected — Index: {idx}")
    )
    win.show()
    sys.exit(app.exec())
