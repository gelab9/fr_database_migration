"""
Dashboard — main application window.

Layout (top → bottom):
  Title bar + user label
  Filter / action bar
  Nav bar  ( |◀  ◀  [Record N of M]  ▶  ▶| )
  ── QSplitter (vertical) ──────────────────
    DetailPanel   (top pane — always-visible report viewer/editor)
    QTableView    (bottom pane — sortable report list)
  ─────────────────────────────────────────
  Status bar
"""

from PyQt6.QtCore import (
    Qt,
    QDateTime,
    QSettings,
    QSortFilterProxyModel,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QFont, QKeySequence, QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from auth.session import AccessLevel, current_user
from db.queries import delete_report, fetch_all_reports, get_connection_info, search_reports
from ui.detail_view import DetailPanel


# ---------------------------------------------------------------------------
# Column definitions
# ---------------------------------------------------------------------------

COLUMNS = [
    ("New ID",        "New ID"),
    ("Project",       "Project"),
    ("Project #",     "Project Number"),
    ("Meter Type",    "Meter Type"),
    ("Serial #",      "Meter Serial Number"),
    ("Test Type",     "Test Type"),
    ("Date Failed",   "Date Failed"),
    ("Tested By",     "Tested By"),
    ("Project Lead",  "Assigned To"),
    ("Pass",          "Pass"),
    ("Anomaly",       "Anomaly"),
    ("FR Approved",   "FR Approved"),
    ("Date Closed",   "Date Closed"),
]

HEADERS = [c[0] for c in COLUMNS]
KEYS    = [c[1] for c in COLUMNS]

COL_APPROVED = KEYS.index("FR Approved")
COL_PASS     = KEYS.index("Pass")
COL_ANOMALY  = KEYS.index("Anomaly")
COL_NEW_ID   = KEYS.index("New ID")

SEARCH_DEBOUNCE_MS      = 300
AUTO_REFRESH_INTERVAL_MS = 60_000

APPROVED_OPTIONS = [("All", None), ("Approved", True), ("Unapproved", False)]

TEST_TYPE_OPTIONS = [
    "All", "EMC", "Reliability", "Functional", "Environmental",
    "Accuracy", "Mechanical", "Safety", "Custom", "Past Tests",
]

SETTINGS_ORG  = "GELab"
SETTINGS_APP  = "FRDatabase"
SETTINGS_COLS = "dashboard/column_widths"
SETTINGS_SPLIT = "dashboard/splitter_sizes"

COLOR_ROW_GREEN  = "#c7e196"
COLOR_ROW_AMBER  = "#fff3cd"
COLOR_ROW_RED    = "#f9c2c2"
COLOR_ROW_YELLOW = "#fffbe6"


# ---------------------------------------------------------------------------
# Numeric-aware sort proxy
# ---------------------------------------------------------------------------

class NumericSortProxyModel(QSortFilterProxyModel):
    def lessThan(self, left, right):
        if left.column() == COL_NEW_ID:
            lv = self.sourceModel().data(left,  Qt.ItemDataRole.UserRole)
            rv = self.sourceModel().data(right, Qt.ItemDataRole.UserRole)
            if isinstance(lv, int) and isinstance(rv, int):
                return lv < rv
        return super().lessThan(left, right)


# ---------------------------------------------------------------------------
# Table model
# ---------------------------------------------------------------------------

class ReportTableModel(QStandardItemModel):
    def __init__(self, parent=None):
        super().__init__(0, len(COLUMNS), parent)
        self.setHorizontalHeaderLabels(HEADERS)
        self._index_col: list[int] = []

    def load(self, reports: list[dict]):
        self.removeRows(0, self.rowCount())
        self._index_col.clear()

        for report in reports:
            row_items = []
            for i, key in enumerate(KEYS):
                raw  = report.get(key)
                text = "" if raw is None else str(raw)
                if "Date" in key and " " in text:
                    text = text.split(" ")[0]
                item = QStandardItem(text)
                item.setEditable(False)
                if i == COL_NEW_ID and raw is not None:
                    try:
                        item.setData(int(raw), Qt.ItemDataRole.UserRole)
                    except (ValueError, TypeError):
                        pass
                row_items.append(item)

            approved = str(report.get("FR_Approved", "") or "").strip()
            passed   = str(report.get("Pass",        "") or "").strip()
            anomaly  = str(report.get("Anomaly",     "") or "").strip()

            if approved == "Checked" and passed == "Checked":
                colour = QColor(COLOR_ROW_GREEN)
            elif approved == "Unchecked":
                colour = QColor(COLOR_ROW_AMBER)
            elif passed == "Unchecked":
                colour = QColor(COLOR_ROW_RED)
            elif anomaly == "Checked":
                colour = QColor(COLOR_ROW_YELLOW)
            else:
                colour = None

            if colour:
                for item in row_items:
                    item.setBackground(colour)

            self.appendRow(row_items)
            self._index_col.append(report.get("Index"))

    def index_for_row(self, row: int) -> int | None:
        if 0 <= row < len(self._index_col):
            return self._index_col[row]
        return None


# ---------------------------------------------------------------------------
# Dashboard window
# ---------------------------------------------------------------------------

class DashboardWindow(QMainWindow):
    """Main application window with embedded split-pane detail view."""

    new_report_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Failure Report Management System")
        self.resize(1440, 900)

        self._model = ReportTableModel(self)
        self._proxy = NumericSortProxyModel(self)
        self._proxy.setSourceModel(self._model)
        self._proxy.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self._apply_filters)

        self._auto_refresh_timer = QTimer(self)
        self._auto_refresh_timer.setInterval(AUTO_REFRESH_INTERVAL_MS)
        self._auto_refresh_timer.timeout.connect(self._on_auto_refresh)

        self._active_filter_clause: str = ""
        self._nav_row: int = -1   # current proxy row (-1 = none)

        self._build_ui()
        self._load_all()
        self._restore_column_widths()
        self._auto_refresh_timer.start()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(6)
        root.setContentsMargins(10, 10, 10, 6)

        # ── Title bar ──────────────────────────────────────────────────
        title_row = QHBoxLayout()
        title_lbl = QLabel("Failure Report Management System")
        tf = QFont()
        tf.setPointSize(13)
        tf.setBold(True)
        title_lbl.setFont(tf)
        title_row.addWidget(title_lbl, stretch=1)

        user_text = (
            f"{current_user.full_name}  [{current_user.access_level.name}]"
            if current_user.is_logged_in else "Not logged in"
        )
        self._user_label = QLabel(user_text)
        self._user_label.setStyleSheet("color: #555; font-size: 9pt;")
        self._user_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        title_row.addWidget(self._user_label)
        root.addLayout(title_row)

        sep0 = QFrame()
        sep0.setFrameShape(QFrame.Shape.HLine)
        sep0.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(sep0)

        # ── Filter / action bar ────────────────────────────────────────
        root.addLayout(self._build_filter_bar())

        # ── Nav bar ────────────────────────────────────────────────────
        root.addLayout(self._build_nav_bar())

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.HLine)
        sep1.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(sep1)

        # ── Main splitter: detail panel (top) + table (bottom) ─────────
        self._splitter = QSplitter(Qt.Orientation.Vertical)
        self._splitter.setHandleWidth(5)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.setObjectName("main_splitter")

        # Detail panel
        self._detail_panel = DetailPanel(self)
        self._detail_panel.setMinimumHeight(200)
        self._detail_panel.report_deleted.connect(self._on_report_deleted)
        self._detail_panel.report_saved.connect(self._on_report_saved)
        self._splitter.addWidget(self._detail_panel)

        # Report table — starts at 1-row height; drag splitter to expand
        self._table = self._build_table()
        self._table.setMinimumHeight(55)
        self._splitter.addWidget(self._table)
        self._splitter.setSizes([680, 80])

        root.addWidget(self._splitter, stretch=1)

        # ── Status bar ─────────────────────────────────────────────────
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._status.showMessage(
            f"Logged in as {current_user.full_name} ({current_user.access_level.name})  |  Loading…"
            if current_user.is_logged_in else "Loading…"
        )

    def _build_filter_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(8)

        bar.addWidget(QLabel("Search:"))
        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText(
            "Search New ID, serial number, description, corrective action…"
        )
        self._search_box.setClearButtonEnabled(True)
        self._search_box.textChanged.connect(self._schedule_search)
        self._search_box.setMinimumWidth(300)
        bar.addWidget(self._search_box, stretch=1)

        bar.addWidget(QLabel("Test Type:"))
        self._test_type_combo = QComboBox()
        self._test_type_combo.addItems(TEST_TYPE_OPTIONS)
        self._test_type_combo.setMinimumWidth(120)
        self._test_type_combo.currentIndexChanged.connect(self._schedule_search)
        bar.addWidget(self._test_type_combo)

        bar.addWidget(QLabel("Approved:"))
        self._approved_combo = QComboBox()
        for label, _ in APPROVED_OPTIONS:
            self._approved_combo.addItem(label)
        self._approved_combo.setMinimumWidth(100)
        self._approved_combo.currentIndexChanged.connect(self._schedule_search)
        bar.addWidget(self._approved_combo)

        self._new_report_btn = QPushButton("+ New Report")
        self._new_report_btn.setObjectName("new_report_btn")
        self._new_report_btn.setFixedWidth(100)
        self._new_report_btn.setShortcut(QKeySequence("Ctrl+N"))
        self._new_report_btn.setToolTip("Create a new failure report  (Ctrl+N)")
        self._new_report_btn.setVisible(current_user.can_create)
        self._new_report_btn.clicked.connect(self.new_report_requested.emit)
        bar.addWidget(self._new_report_btn)

        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setObjectName("delete_btn")
        self._delete_btn.setFixedWidth(70)
        self._delete_btn.setShortcut(QKeySequence("Delete"))
        self._delete_btn.setEnabled(False)
        self._delete_btn.setVisible(current_user.can_delete)
        self._delete_btn.clicked.connect(self._on_delete_clicked)
        bar.addWidget(self._delete_btn)

        self._adv_filter_btn = QPushButton("Advanced Filter")
        self._adv_filter_btn.setObjectName("adv_filter_btn")
        self._adv_filter_btn.clicked.connect(self._on_advanced_filter_clicked)
        bar.addWidget(self._adv_filter_btn)

        self._clear_filter_btn = QPushButton("Clear Filter")
        self._clear_filter_btn.setObjectName("clear_filter_btn")
        self._clear_filter_btn.setVisible(False)
        self._clear_filter_btn.clicked.connect(self._on_clear_filter_clicked)
        bar.addWidget(self._clear_filter_btn)

        if current_user.access_level >= AccessLevel.ADMIN:
            btn = QPushButton("Lookups")
            btn.setObjectName("admin_btn")
            btn.setToolTip("Manage lookup table values (ADMIN only)")
            btn.clicked.connect(self._on_admin_clicked)
            bar.addWidget(btn)

            users_btn = QPushButton("Users")
            users_btn.setObjectName("admin_btn")
            users_btn.setToolTip("Manage user accounts (ADMIN only)")
            users_btn.clicked.connect(self._on_manage_users_clicked)
            bar.addWidget(users_btn)

        if current_user.access_level >= AccessLevel.CREATE_NEW:
            btn = QPushButton("Test Equipment")
            btn.setObjectName("equip_btn")
            btn.clicked.connect(self._on_test_equipment_clicked)
            bar.addWidget(btn)

        return bar

    def _build_nav_bar(self) -> QHBoxLayout:
        """Navigation bar: |◀ ◀ [Record N of M] ▶ ▶|  Refresh"""
        bar = QHBoxLayout()
        bar.setSpacing(4)

        btn_style = "QPushButton { font-size: 13pt; padding: 0 6px; min-width: 28px; }"

        self._nav_first = QPushButton("|◀")
        self._nav_first.setObjectName("nav_btn")
        self._nav_first.setToolTip("First record")
        self._nav_first.setStyleSheet(btn_style)
        self._nav_first.clicked.connect(lambda: self._nav_jump(0))
        bar.addWidget(self._nav_first)

        self._nav_prev = QPushButton("◀")
        self._nav_prev.setObjectName("nav_btn")
        self._nav_prev.setToolTip("Previous record")
        self._nav_prev.setStyleSheet(btn_style)
        self._nav_prev.clicked.connect(self._nav_go_prev)
        bar.addWidget(self._nav_prev)

        self._nav_label = QLabel("No records")
        self._nav_label.setObjectName("nav_label")
        self._nav_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._nav_label.setMinimumWidth(160)
        self._nav_label.setStyleSheet("font-size: 9pt; color: #444;")
        bar.addWidget(self._nav_label)

        self._nav_next = QPushButton("▶")
        self._nav_next.setObjectName("nav_btn")
        self._nav_next.setToolTip("Next record")
        self._nav_next.setStyleSheet(btn_style)
        self._nav_next.clicked.connect(self._nav_go_next)
        bar.addWidget(self._nav_next)

        self._nav_last = QPushButton("▶|")
        self._nav_last.setObjectName("nav_btn")
        self._nav_last.setToolTip("Last record")
        self._nav_last.setStyleSheet(btn_style)
        self._nav_last.clicked.connect(lambda: self._nav_jump(self._proxy.rowCount() - 1))
        bar.addWidget(self._nav_last)

        bar.addSpacing(16)

        self._refresh_btn = QPushButton("⟳  Refresh")
        self._refresh_btn.setFixedWidth(90)
        self._refresh_btn.setShortcut(QKeySequence("F5"))
        self._refresh_btn.setToolTip("Reload all reports  (F5)")
        self._refresh_btn.clicked.connect(self._load_all)
        bar.addWidget(self._refresh_btn)

        bar.addStretch()
        return bar

    def _build_table(self) -> QTableView:
        table = QTableView()
        table.setModel(self._proxy)
        table.setSortingEnabled(True)
        table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setHighlightSections(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        table.setShowGrid(True)
        table.setWordWrap(False)
        table.setMinimumHeight(120)

        defaults = {
            "New ID": 65, "Project": 120, "Project #": 80, "Meter Type": 120,
            "Serial #": 120, "Test Type": 95, "Date Failed": 90, "Tested By": 105,
            "Project Lead": 105, "Pass": 50, "Anomaly": 60, "FR Approved": 90,
            "Date Closed": 90,
        }
        for i, hdr in enumerate(HEADERS):
            if hdr in defaults:
                table.setColumnWidth(i, defaults[hdr])

        # Single-click → load report in detail panel
        table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        # Double-click → same (already handled by selectionChanged, but keep for compat)
        table.doubleClicked.connect(self._on_row_double_clicked)
        table.horizontalHeader().sectionResized.connect(self._save_column_widths)

        return table

    # ------------------------------------------------------------------
    # Column width persistence
    # ------------------------------------------------------------------

    def _save_column_widths(self):
        s = QSettings(SETTINGS_ORG, SETTINGS_APP)
        s.setValue(SETTINGS_COLS, [self._table.columnWidth(i) for i in range(len(HEADERS))])

    def _restore_column_widths(self):
        s = QSettings(SETTINGS_ORG, SETTINGS_APP)
        widths = s.value(SETTINGS_COLS)
        if widths and len(widths) == len(HEADERS):
            for i, w in enumerate(widths):
                try:
                    self._table.setColumnWidth(i, int(w))
                except (ValueError, TypeError):
                    pass

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _nav_jump(self, proxy_row: int):
        total = self._proxy.rowCount()
        if total == 0:
            return
        proxy_row = max(0, min(proxy_row, total - 1))
        self._table.selectRow(proxy_row)
        self._table.scrollTo(self._proxy.index(proxy_row, 0))

    def _nav_go_prev(self):
        self._nav_jump(max(0, self._nav_row - 1))

    def _nav_go_next(self):
        self._nav_jump(self._nav_row + 1)

    def _update_nav_label(self):
        total = self._proxy.rowCount()
        if total == 0 or self._nav_row < 0:
            self._nav_label.setText(f"0 of {total}")
        else:
            self._nav_label.setText(f"Record {self._nav_row + 1} of {total}")
        self._nav_first.setEnabled(self._nav_row > 0)
        self._nav_prev.setEnabled(self._nav_row > 0)
        self._nav_next.setEnabled(self._nav_row < total - 1)
        self._nav_last.setEnabled(self._nav_row < total - 1)

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def _on_selection_changed(self):
        selected = self._table.selectionModel().selectedRows()
        has_sel  = bool(selected)
        self._delete_btn.setEnabled(has_sel)

        if has_sel:
            proxy_row    = selected[0].row()
            self._nav_row = proxy_row
            source_index = self._proxy.mapToSource(self._proxy.index(proxy_row, 0))
            db_index     = self._model.index_for_row(source_index.row())
            if db_index is not None:
                self._detail_panel.load_report(db_index)
        else:
            self._nav_row = -1
            self._detail_panel.clear()

        self._update_nav_label()

    def _on_row_double_clicked(self, _):
        # Selection already handled by selectionChanged; ensure detail page is visible
        self._detail_panel._stacked.setCurrentIndex(1)

    def _selected_db_index(self) -> int | None:
        selected = self._table.selectionModel().selectedRows()
        if not selected:
            return None
        source_index = self._proxy.mapToSource(selected[0])
        return self._model.index_for_row(source_index.row())

    # ------------------------------------------------------------------
    # Report deleted / saved callbacks from DetailPanel
    # ------------------------------------------------------------------

    def _on_report_deleted(self, _: int):
        self._load_all()

    def _on_report_saved(self):
        # Refresh the table row colours without losing selection
        current_row = self._nav_row
        if self._active_filter_clause:
            from db.queries import search_with_filter
            rows = search_with_filter(self._active_filter_clause)
        else:
            rows = fetch_all_reports()
        self._model.load(rows)
        self._proxy.sort(
            self._table.horizontalHeader().sortIndicatorSection(),
            self._table.horizontalHeader().sortIndicatorOrder(),
        )
        # Re-select the same row
        if 0 <= current_row < self._proxy.rowCount():
            self._table.selectRow(current_row)

    # ------------------------------------------------------------------
    # Dialog launchers
    # ------------------------------------------------------------------

    def _on_admin_clicked(self):
        from ui.manage_lookups import open_manage_lookups
        open_manage_lookups(parent=self)

    def _on_manage_users_clicked(self):
        from ui.manage_users import open_manage_users
        open_manage_users(parent=self)

    def _on_test_equipment_clicked(self):
        from ui.test_equipment import open_test_equipment
        open_test_equipment(parent=self)

    # ------------------------------------------------------------------
    # Advanced filter
    # ------------------------------------------------------------------

    def _on_advanced_filter_clicked(self):
        from ui.filter_dialog import FilterDialog
        dlg = FilterDialog(initial_clause=self._active_filter_clause, parent=self)
        if dlg.exec() == FilterDialog.DialogCode.Accepted:
            self._active_filter_clause = dlg.result_clause
            self._model.load(dlg.result_rows)
            self._proxy.sort(
                self._table.horizontalHeader().sortIndicatorSection(),
                self._table.horizontalHeader().sortIndicatorOrder(),
            )
            count = self._model.rowCount()
            short = (self._active_filter_clause[:60] + "…"
                     if len(self._active_filter_clause) > 60
                     else self._active_filter_clause)
            self._status.showMessage(
                f"{count} report{'s' if count != 1 else ''} matched."
                + (f"  |  Filter: {short}" if short else "")
            )
            self._clear_filter_btn.setVisible(bool(self._active_filter_clause))
            self._nav_row = -1
            self._update_nav_label()

    def _on_clear_filter_clicked(self):
        self._active_filter_clause = ""
        self._clear_filter_btn.setVisible(False)
        self._load_all()

    # ------------------------------------------------------------------
    # Delete (from toolbar — same as detail panel delete but from grid)
    # ------------------------------------------------------------------

    def _on_delete_clicked(self):
        db_index = self._selected_db_index()
        if db_index is None:
            return

        selected  = self._table.selectionModel().selectedRows()
        proxy_row = selected[0].row()
        new_id    = self._proxy.data(self._proxy.index(proxy_row, COL_NEW_ID))
        project   = self._proxy.data(self._proxy.index(proxy_row, KEYS.index("Project")))
        label     = f"FR{new_id}" + (f" — {project}" if project else "")

        if QMessageBox.question(
            self, "Delete Report",
            f"Permanently delete <b>{label}</b>?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        ) != QMessageBox.StandardButton.Yes:
            return

        if QMessageBox.question(
            self, "Confirm Delete",
            f"Final confirmation — delete <b>{label}</b>?\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        ) != QMessageBox.StandardButton.Yes:
            return

        if delete_report(db_index):
            self._detail_panel.clear()
            self._status.showMessage(f"Deleted {label}.")
            self._load_all()
        else:
            QMessageBox.critical(self, "Delete Failed", f"Could not delete {label}.")

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_all(self):
        self._status.showMessage("Loading all reports…")
        QApplication.processEvents()
        reports = fetch_all_reports()
        self._model.load(reports)
        self._proxy.sort(COL_NEW_ID, Qt.SortOrder.AscendingOrder)
        count = self._model.rowCount()
        ts    = QDateTime.currentDateTime().toString("h:mm:ss AP")
        info  = get_connection_info()
        srv   = info.get("actual_server") or info.get("config_server") or "?"
        db    = info.get("actual_database") or info.get("config_database") or "?"
        self._status.showMessage(
            f"{count} report{'s' if count != 1 else ''} loaded.  |  "
            f"Refreshed: {ts}  |  Auto: {AUTO_REFRESH_INTERVAL_MS // 1000}s  |  "
            f"Server: {srv}  DB: {db}"
        )
        self._nav_row = -1
        self._update_nav_label()

    def _on_auto_refresh(self):
        if self._debounce.isActive():
            return
        current_row = self._nav_row
        if self._active_filter_clause:
            from db.queries import search_with_filter
            rows = search_with_filter(self._active_filter_clause)
            self._model.load(rows)
            self._proxy.sort(
                self._table.horizontalHeader().sortIndicatorSection(),
                self._table.horizontalHeader().sortIndicatorOrder(),
            )
            ts = QDateTime.currentDateTime().toString("h:mm:ss AP")
            short = (self._active_filter_clause[:50] + "…"
                     if len(self._active_filter_clause) > 50
                     else self._active_filter_clause)
            self._status.showMessage(
                f"{self._model.rowCount()} matched.  |  Filter: {short}  |  {ts}"
            )
        else:
            self._load_all()
        # Restore row selection if still valid
        if 0 <= current_row < self._proxy.rowCount():
            self._table.selectRow(current_row)
        self._update_nav_label()

    def _schedule_search(self):
        self._debounce.start(SEARCH_DEBOUNCE_MS)

    def _apply_filters(self):
        search_text      = self._search_box.text().strip()
        test_type_label  = self._test_type_combo.currentText()
        approved_idx     = self._approved_combo.currentIndex()
        test_type        = "" if test_type_label == "All" else test_type_label
        _, approved_val  = APPROVED_OPTIONS[approved_idx]

        self._status.showMessage("Searching…")
        QApplication.processEvents()

        reports = search_reports(
            search_text=search_text, test_type=test_type, approved=approved_val
        )
        self._model.load(reports)
        self._proxy.sort(
            self._table.horizontalHeader().sortIndicatorSection(),
            self._table.horizontalHeader().sortIndicatorOrder(),
        )
        self._nav_row = -1
        self._update_nav_label()
        self._status.showMessage(
            f"{self._model.rowCount()} report{'s' if self._model.rowCount() != 1 else ''} matched."
        )

    # ------------------------------------------------------------------
    # Window close
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        self._save_column_widths()
        super().closeEvent(event)
