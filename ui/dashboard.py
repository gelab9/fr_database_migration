"""
Dashboard window — main entry point for the FR management application.

Displays a searchable, sortable table of all failure reports. Filters call
search_reports() in real time. Clicking a row emits report_selected(index)
so the detail/edit view can be opened by the parent application.

Day 3 changes
-------------
* New ID column sorts numerically via a custom QSortFilterProxyModel that
  stores the raw int in Qt.ItemDataRole.UserRole alongside the display text.
* Row colour logic updated: Pass/Anomaly use 'Checked'/'Unchecked' (same
  encoding as FR_Approved), not 'no'/'false' text strings.
* Delete button added to the filter bar — fires delete_report() after a
  two-step confirmation dialog, then refreshes the dashboard.
* Keyboard shortcuts: Ctrl+N (new report), Del (delete selected row),
  F5 (refresh), Escape closes focus from search box.
* Column widths are saved to QSettings and restored on next launch.
* objectName set on action buttons so style.qss selectors fire correctly.
* Row colours updated to approved palette:
    green  #c7e196  fully approved + passed
    amber  #fff3cd  pending approval
    red    #f9c2c2  open failure
    yellow #fffbe6  anomaly flagged
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
    QStatusBar,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from auth.session import AccessLevel, current_user
from db.queries import delete_report, fetch_all_reports, get_connection_info, search_reports


# ---------------------------------------------------------------------------
# Column definitions
# ---------------------------------------------------------------------------

# (display header, dict key from query result)
COLUMNS = [
    ("New ID",          "New ID"),
    ("Project",         "Project"),
    ("Project #",       "Project Number"),
    ("Meter Type",      "Meter Type"),
    ("Serial Number",   "Meter Serial Number"),
    ("Test Type",       "Test Type"),
    ("Date Failed",     "Date Failed"),
    ("Tested By",       "Tested By"),
    ("Assigned To",     "Assigned To"),
    ("Pass",            "Pass"),
    ("Anomaly",         "Anomaly"),
    ("FR Approved",     "FR Approved"),
    ("Date Closed",     "Date Closed"),
]

HEADERS = [col[0] for col in COLUMNS]
KEYS    = [col[1] for col in COLUMNS]

# Column indices used for conditional row colouring
COL_APPROVED = KEYS.index("FR Approved")
COL_PASS     = KEYS.index("Pass")
COL_ANOMALY  = KEYS.index("Anomaly")

# Index of the New ID column (needs numeric sort treatment)
COL_NEW_ID   = KEYS.index("New ID")

# Debounce delay (ms) before firing a search query after the user types
SEARCH_DEBOUNCE_MS = 300

# Auto-refresh interval — keeps all engineers' dashboards in sync without manual F5
AUTO_REFRESH_INTERVAL_MS = 60_000   # 60 seconds

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

# QSettings identifiers
SETTINGS_ORG  = "GELab"
SETTINGS_APP  = "FRDatabase"
SETTINGS_COLS = "dashboard/column_widths"

# ---------------------------------------------------------------------------
# Approved row colour palette
# ---------------------------------------------------------------------------
COLOR_ROW_GREEN  = "#c7e196"   # FR Approved + Pass both Checked — fully complete
COLOR_ROW_AMBER  = "#fff3cd"   # FR Approved = Unchecked — pending approval
COLOR_ROW_RED    = "#f9c2c2"   # Pass = Unchecked — open failure
COLOR_ROW_YELLOW = "#fffbe6"   # Anomaly = Checked — anomaly flagged


# ---------------------------------------------------------------------------
# Numeric-aware sort proxy
# ---------------------------------------------------------------------------

class NumericSortProxyModel(QSortFilterProxyModel):
    """
    Proxy that sorts the New ID column numerically by reading the int stored
    in Qt.ItemDataRole.UserRole, while all other columns sort by display text.
    """

    def lessThan(self, left, right):
        if left.column() == COL_NEW_ID:
            lv = self.sourceModel().data(left,  Qt.ItemDataRole.UserRole)
            rv = self.sourceModel().data(right, Qt.ItemDataRole.UserRole)
            # Fall back to text sort if UserRole data is not available
            if isinstance(lv, int) and isinstance(rv, int):
                return lv < rv
        return super().lessThan(left, right)


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
            for i, key in enumerate(KEYS):
                raw = report.get(key)
                text = "" if raw is None else str(raw)

                # Strip time component from date columns so they read cleanly
                if "Date" in key and " " in text:
                    text = text.split(" ")[0]

                item = QStandardItem(text)
                item.setEditable(False)

                # Store the raw integer for New ID so the proxy can sort numerically
                if i == COL_NEW_ID and raw is not None:
                    try:
                        item.setData(int(raw), Qt.ItemDataRole.UserRole)
                    except (ValueError, TypeError):
                        pass

                row_items.append(item)

            # ------------------------------------------------------------------
            # Row-level colour hints
            #
            # All three flag columns (FR Approved, Pass, Anomaly) are stored as
            # nvarchar with values 'Checked' or 'Unchecked' (matching the VB
            # CheckBox serialisation used throughout the legacy system).
            #
            # Priority (highest → lowest):
            #   1. green  — fully complete   (FR Approved AND Pass = Checked)
            #   2. amber  — pending approval (FR Approved = Unchecked)
            #   3. red    — open failure      (Pass = Unchecked)
            #   4. yellow — anomaly flagged   (Anomaly = Checked)
            #   (no colour when no flags are set)
            # ------------------------------------------------------------------
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
    new_report_requested :
        Emitted when the user clicks "+ New Report".
    """

    report_selected      = pyqtSignal(int)
    new_report_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Failure Report Management System")
        self.resize(1400, 800)

        self._model = ReportTableModel(self)
        self._proxy = NumericSortProxyModel(self)
        self._proxy.setSourceModel(self._model)
        self._proxy.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

        # Debounce timer so we don't query on every keystroke
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self._apply_filters)

        # Auto-refresh timer — keeps all engineers in sync without manual F5
        self._auto_refresh_timer = QTimer(self)
        self._auto_refresh_timer.setInterval(AUTO_REFRESH_INTERVAL_MS)
        self._auto_refresh_timer.timeout.connect(self._on_auto_refresh)

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
        root.setSpacing(8)
        root.setContentsMargins(12, 12, 12, 12)

        # ── Title bar ──────────────────────────────────────────────────
        title_row = QHBoxLayout()

        title = QLabel("Failure Report Management System")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        title_row.addWidget(title, stretch=1)

        # Show logged-in user + access level on the right side of the title bar
        user_text = (
            f"{current_user.full_name}  [{current_user.access_level.name}]"
            if current_user.is_logged_in
            else "Not logged in"
        )
        self._user_label = QLabel(user_text)
        self._user_label.setStyleSheet("color: #555; font-size: 9pt;")
        self._user_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        title_row.addWidget(self._user_label)

        root.addLayout(title_row)

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

        # New Report button (Ctrl+N) — hidden for READ_ONLY / NO_ACCESS users
        self._new_report_btn = QPushButton("+ New Report")
        self._new_report_btn.setObjectName("new_report_btn")
        self._new_report_btn.setFixedWidth(100)
        self._new_report_btn.setShortcut(QKeySequence("Ctrl+N"))
        self._new_report_btn.setToolTip("Create a new failure report  (Ctrl+N)")
        self._new_report_btn.setVisible(current_user.can_create)
        self._new_report_btn.clicked.connect(self.new_report_requested.emit)
        filter_bar.addWidget(self._new_report_btn)

        # Delete button (Del key) — ADMIN only (matches VB eAccessState.ADMIN gate)
        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setObjectName("delete_btn")
        self._delete_btn.setFixedWidth(70)
        self._delete_btn.setShortcut(QKeySequence("Delete"))
        self._delete_btn.setToolTip("Delete selected report  (Del)")
        self._delete_btn.setEnabled(False)   # enabled only when a row is selected
        self._delete_btn.setVisible(current_user.can_delete)
        self._delete_btn.clicked.connect(self._on_delete_clicked)
        filter_bar.addWidget(self._delete_btn)

        # Advanced Filter button — opens FilterDialog (frmFilter.vb port)
        self._adv_filter_btn = QPushButton("Advanced Filter")
        self._adv_filter_btn.setObjectName("adv_filter_btn")
        self._adv_filter_btn.setToolTip("Open the advanced filter dialog")
        self._adv_filter_btn.clicked.connect(self._on_advanced_filter_clicked)
        filter_bar.addWidget(self._adv_filter_btn)

        # Clear Filter — only visible while an advanced filter is active
        self._clear_filter_btn = QPushButton("Clear Filter")
        self._clear_filter_btn.setObjectName("clear_filter_btn")
        self._clear_filter_btn.setToolTip("Remove the active advanced filter and reload all reports")
        self._clear_filter_btn.setVisible(False)
        self._clear_filter_btn.clicked.connect(self._on_clear_filter_clicked)
        filter_bar.addWidget(self._clear_filter_btn)

        # Admin button — ADMIN only: manage lookup tables
        if current_user.access_level >= AccessLevel.ADMIN:
            self._admin_btn = QPushButton("Admin")
            self._admin_btn.setObjectName("admin_btn")
            self._admin_btn.setToolTip("Manage lookup table values (ADMIN only)")
            self._admin_btn.clicked.connect(self._on_admin_clicked)
            filter_bar.addWidget(self._admin_btn)

        # Test Equipment button — opens equipment management (POWER+ users)
        if current_user.access_level >= AccessLevel.CREATE_NEW:
            self._equip_btn = QPushButton("Test Equipment")
            self._equip_btn.setObjectName("equip_btn")
            self._equip_btn.setToolTip("Manage test equipment inventory")
            self._equip_btn.clicked.connect(self._on_test_equipment_clicked)
            filter_bar.addWidget(self._equip_btn)

        # Refresh button (F5)
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setFixedWidth(80)
        self._refresh_btn.setShortcut(QKeySequence("F5"))
        self._refresh_btn.setToolTip("Reload all reports from the database  (F5)")
        self._refresh_btn.clicked.connect(self._load_all)
        filter_bar.addWidget(self._refresh_btn)

        root.addLayout(filter_bar)

        # Active advanced filter clause (empty string = no filter)
        self._active_filter_clause: str = ""

        # ── Table ──────────────────────────────────────────────────────
        self._table = QTableView()
        self._table.setModel(self._proxy)
        self._table.setSortingEnabled(True)
        self._table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
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
        self._default_widths = {
            "New ID":        70,
            "Project":      120,
            "Project #":     90,
            "Meter Type":   130,
            "Serial Number":130,
            "Test Type":    100,
            "Date Failed":   95,
            "Tested By":    110,
            "Assigned To":  110,
            "Pass":          55,
            "Anomaly":       65,
            "FR Approved":   95,
            "Date Closed":   95,
        }
        for i, header in enumerate(HEADERS):
            if header in self._default_widths:
                self._table.setColumnWidth(i, self._default_widths[header])

        self._table.doubleClicked.connect(self._on_row_double_clicked)

        # Enable/disable Delete button based on selection
        self._table.selectionModel().selectionChanged.connect(self._on_selection_changed)

        # Save column widths when the user resizes them
        self._table.horizontalHeader().sectionResized.connect(self._save_column_widths)

        root.addWidget(self._table)

        # ── Status bar ─────────────────────────────────────────────────
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        access_msg = (
            f"Logged in as {current_user.full_name} ({current_user.access_level.name})  |  Loading…"
            if current_user.is_logged_in
            else "Loading…"
        )
        self._status.showMessage(access_msg)

    # ------------------------------------------------------------------
    # Column width persistence
    # ------------------------------------------------------------------

    def _save_column_widths(self):
        settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        widths = [self._table.columnWidth(i) for i in range(len(HEADERS))]
        settings.setValue(SETTINGS_COLS, widths)

    def _restore_column_widths(self):
        settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        widths = settings.value(SETTINGS_COLS)
        if widths and len(widths) == len(HEADERS):
            for i, w in enumerate(widths):
                try:
                    self._table.setColumnWidth(i, int(w))
                except (ValueError, TypeError):
                    pass

    # ------------------------------------------------------------------
    # Test Equipment
    # ------------------------------------------------------------------

    def _on_admin_clicked(self):
        from ui.manage_lookups import open_manage_lookups
        open_manage_lookups(parent=self)

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
            rows = dlg.result_rows
            self._model.load(rows)
            self._proxy.sort(
                self._table.horizontalHeader().sortIndicatorSection(),
                self._table.horizontalHeader().sortIndicatorOrder(),
            )
            count = self._model.rowCount()
            clause_summary = (
                f"  |  Filter: {self._active_filter_clause[:60]}…"
                if len(self._active_filter_clause) > 60
                else (f"  |  Filter: {self._active_filter_clause}" if self._active_filter_clause else "")
            )
            self._status.showMessage(f"{count} report{'s' if count != 1 else ''} matched.{clause_summary}")
            self._clear_filter_btn.setVisible(bool(self._active_filter_clause))

    def _on_clear_filter_clicked(self):
        self._active_filter_clause = ""
        self._clear_filter_btn.setVisible(False)
        self._load_all()

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_all(self):
        """Fetch every report (no filters) and populate the table."""
        self._status.showMessage("Loading all reports…")
        QApplication.processEvents()
        reports = fetch_all_reports()
        self._model.load(reports)
        self._proxy.sort(COL_NEW_ID, Qt.SortOrder.AscendingOrder)
        count = self._model.rowCount()
        ts = QDateTime.currentDateTime().toString("h:mm:ss AP")
        info = get_connection_info()
        server_label = info.get("actual_server") or info.get("config_server") or "?"
        db_label     = info.get("actual_database") or info.get("config_database") or "?"
        self._status.showMessage(
            f"{count} report{'s' if count != 1 else ''} loaded.  |  "
            f"Last refreshed: {ts}  |  Auto-refresh: {AUTO_REFRESH_INTERVAL_MS // 1000}s  |  "
            f"Server: {server_label}  DB: {db_label}"
        )

    def _on_auto_refresh(self):
        """
        Fired by the auto-refresh timer every AUTO_REFRESH_INTERVAL_MS ms.
        Re-applies whichever data is currently shown so all engineers stay in sync.
        Skips silently if a debounce search is pending to avoid conflicting queries.
        """
        if self._debounce.isActive():
            return
        if self._active_filter_clause:
            # Re-run the active advanced filter
            from db.queries import search_with_filter
            rows = search_with_filter(self._active_filter_clause)
            self._model.load(rows)
            self._proxy.sort(
                self._table.horizontalHeader().sortIndicatorSection(),
                self._table.horizontalHeader().sortIndicatorOrder(),
            )
            count = self._model.rowCount()
            ts = QDateTime.currentDateTime().toString("h:mm:ss AP")
            clause_summary = (
                f"{self._active_filter_clause[:50]}…"
                if len(self._active_filter_clause) > 50
                else self._active_filter_clause
            )
            self._status.showMessage(
                f"{count} report{'s' if count != 1 else ''} matched.  |  "
                f"Filter: {clause_summary}  |  Last refreshed: {ts}"
            )
        else:
            self._load_all()

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
    # Selection handling
    # ------------------------------------------------------------------

    def _on_selection_changed(self):
        has_selection = self._table.selectionModel().hasSelection()
        self._delete_btn.setEnabled(has_selection)

    def _selected_db_index(self) -> int | None:
        """Return the [Index] PK of the currently selected row, or None."""
        selected = self._table.selectionModel().selectedRows()
        if not selected:
            return None
        proxy_index = selected[0]
        source_index = self._proxy.mapToSource(proxy_index)
        return self._model.index_for_row(source_index.row())

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def _on_delete_clicked(self):
        db_index = self._selected_db_index()
        if db_index is None:
            return

        selected = self._table.selectionModel().selectedRows()
        proxy_row = selected[0].row()
        new_id_item = self._proxy.data(
            self._proxy.index(proxy_row, COL_NEW_ID)
        )
        project_item = self._proxy.data(
            self._proxy.index(proxy_row, KEYS.index("Project"))
        )
        label = f"FR #{new_id_item}" + (f" — {project_item}" if project_item else "")

        confirm1 = QMessageBox(self)
        confirm1.setWindowTitle("Delete Report")
        confirm1.setIcon(QMessageBox.Icon.Warning)
        confirm1.setText(f"Are you sure you want to delete\n<b>{label}</b>?")
        confirm1.setInformativeText(
            "This will permanently remove the report and any associated "
            "attachments from the database. This action cannot be undone."
        )
        confirm1.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
        )
        confirm1.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if confirm1.exec() != QMessageBox.StandardButton.Yes:
            return

        confirm2 = QMessageBox(self)
        confirm2.setWindowTitle("Confirm Permanent Delete")
        confirm2.setIcon(QMessageBox.Icon.Critical)
        confirm2.setText("This is your final confirmation.")
        confirm2.setInformativeText(
            f"Permanently delete <b>{label}</b>?\n\nThis cannot be undone."
        )
        confirm2.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
        )
        confirm2.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if confirm2.exec() != QMessageBox.StandardButton.Yes:
            return

        success = delete_report(db_index)
        if success:
            self._status.showMessage(f"Deleted {label}.")
            self._load_all()
        else:
            QMessageBox.critical(
                self, "Delete Failed",
                f"Could not delete {label}.\n\n"
                "The record may have already been removed, or a database error occurred."
            )

    # ------------------------------------------------------------------
    # Row double-click → open detail
    # ------------------------------------------------------------------

    def _on_row_double_clicked(self, proxy_index):
        """Map the proxy row back to the source model to get [Index]."""
        source_index = self._proxy.mapToSource(proxy_index)
        db_index = self._model.index_for_row(source_index.row())
        if db_index is not None:
            self.report_selected.emit(db_index)

    # ------------------------------------------------------------------
    # Window close — save column widths one final time
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        self._save_column_widths()
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# Standalone entry point (dev / testing)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    from pathlib import Path
    _project_root = Path(__file__).resolve().parent.parent
    if str(_project_root) not in sys.path:
        sys.path.insert(0, str(_project_root))

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = DashboardWindow()
    from ui.detail_view import open_detail
    win.report_selected.connect(lambda idx: open_detail(idx, parent=win))
    win.show()
    sys.exit(app.exec())