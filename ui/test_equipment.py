"""
Test Equipment Management dialog — mirrors frmSelectTestEquipment.vb.

Opens from the dashboard "Test Equipment" button.  POWER+ users can add,
revise (update calibration), and obsolete equipment.  ADMIN users can also
edit all fields.  READ_ONLY / CREATE_NEW users see the table read-only.

Access levels (matching VB eTestEquipmentState):
  ADMIN       → New, Edit, Revise, Obsolete
  POWER       → New, Revise, Obsolete
  CREATE_NEW  → Revise only
  READ_ONLY   → View only

Revision model (matching VB):
  [ID]          — same across all revisions of a piece of equipment
  [REV]         — incremented integer; 0 for the first entry
  [ACTIVE REV]  — only ONE revision per ID is True at a time
  [OBSOLETE]    — soft-delete flag; obsolete equipment is hidden by default
"""

from datetime import date as _date

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from auth.session import AccessLevel, current_user
from db.equipment_queries import (
    create_equipment,
    fetch_all_equipment,
    fetch_equipment_revisions,
    fetch_equipment_types,
    get_max_equipment_id,
    obsolete_equipment,
    revise_equipment,
    update_equipment,
)

# ---------------------------------------------------------------------------
# Table column definitions  (display header, DB column name)
# ---------------------------------------------------------------------------

_LIST_COLUMNS: list[tuple[str, str]] = [
    ("ID",           "ID"),
    ("Rev",          "REV"),
    ("Type",         "TYPE"),
    ("Manufacturer", "MANUFACTURER"),
    ("Model",        "MODEL"),
    ("Serial #",     "SERIAL NUMBER"),
    ("Lab ID",       "LAB ID"),
    ("Last Cal",     "LAST CAL"),
    ("Next Cal",     "NEXT CAL"),
    ("Active Rev",   "ACTIVE REV"),
    ("Cal Req",      "CAL REQ"),
]

_LIST_HEADERS = [c[0] for c in _LIST_COLUMNS]
_LIST_KEYS    = [c[1] for c in _LIST_COLUMNS]

# Detail-pane form fields  (label, DB column)
_DETAIL_FIELDS: list[tuple[str, str]] = [
    ("ID",               "ID"),
    ("Rev",              "REV"),
    ("Type",             "TYPE"),
    ("Manufacturer",     "MANUFACTURER"),
    ("Model",            "MODEL"),
    ("Serial Number",    "SERIAL NUMBER"),
    ("Alt Serial #",     "ALT SERIAL NUMBER"),
    ("Lab ID",           "LAB ID"),
    ("Location",         "LOCATION"),
    ("Last Cal",         "LAST CAL"),
    ("Next Cal",         "NEXT CAL"),
    ("Cal Required",     "CAL REQ"),
    ("Active Rev",       "ACTIVE REV"),
    ("Obsolete",         "OBSOLETE"),
    ("Test Group",       "TEST GROUP"),
    ("Group Members",    "TEST GROUP MEMBERS"),
    ("Note",             "NOTE"),
    ("Description",      "DESCRIPTION"),
]

_BIT_KEYS   = {"CAL REQ", "ACTIVE REV", "OBSOLETE", "TEST GROUP"}
_MULTI_KEYS = {"NOTE", "DESCRIPTION"}


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------

class TestEquipmentDialog(QDialog):
    """
    Test Equipment Management — view, add, edit, revise, and obsolete
    equipment in the METER_SPECS.TEST_EQUIPMENT table.
    """

    def __init__(self, parent=None, select_mode: bool = False):
        """
        Parameters
        ----------
        select_mode : bool
            When True a "Select" button is shown; closing with it sets
            self.selected_equipment_id to the chosen equipment [ID].
        """
        super().__init__(parent)
        self.selected_equipment_id: int | None = None
        self._select_mode = select_mode
        self._current_row_index: int | None = None  # [INDEX] PK of table-selected row
        self._current_data: list[dict] = []          # current query results
        self._editing = False
        self._new_mode = False
        self._revise_mode = False

        self.setWindowTitle("Test Equipment Management")
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        self.resize(1100, 700)
        self._build_ui()
        self._load_equipment()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(6)
        root.setContentsMargins(10, 10, 10, 10)

        # ── Title ────────────────────────────────────────────────────────
        title = QLabel("Test Equipment")
        f = QFont()
        f.setPointSize(13)
        f.setBold(True)
        title.setFont(f)
        root.addWidget(title)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(sep)

        # ── Filter bar ───────────────────────────────────────────────────
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)

        filter_row.addWidget(QLabel("Type:"))
        self._type_combo = QComboBox()
        self._type_combo.addItem("All Types")
        self._type_combo.addItems(fetch_equipment_types())
        self._type_combo.setMinimumWidth(140)
        self._type_combo.currentIndexChanged.connect(self._on_filter_changed)
        filter_row.addWidget(self._type_combo)

        self._chk_show_inactive = QCheckBox("Show Inactive Revisions")
        self._chk_show_inactive.stateChanged.connect(self._on_filter_changed)
        filter_row.addWidget(self._chk_show_inactive)

        self._chk_show_obsolete = QCheckBox("Show Obsolete")
        self._chk_show_obsolete.stateChanged.connect(self._on_filter_changed)
        filter_row.addWidget(self._chk_show_obsolete)

        filter_row.addStretch()

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setFixedWidth(80)
        refresh_btn.clicked.connect(self._load_equipment)
        filter_row.addWidget(refresh_btn)

        root.addLayout(filter_row)

        # ── Splitter: table (top) + detail pane (bottom) ─────────────────
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)

        # Equipment table
        self._table = QTableWidget(0, len(_LIST_COLUMNS))
        self._table.setHorizontalHeaderLabels(_LIST_HEADERS)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        self._table.setMinimumHeight(200)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._table.doubleClicked.connect(self._on_table_double_clicked)
        splitter.addWidget(self._table)

        # Detail pane
        splitter.addWidget(self._build_detail_pane())
        splitter.setSizes([350, 300])
        root.addWidget(splitter, stretch=1)

        # ── Action buttons ───────────────────────────────────────────────
        root.addWidget(self._build_action_buttons())

    def _build_detail_pane(self) -> QWidget:
        gb = QGroupBox("Equipment Details")
        outer = QVBoxLayout(gb)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        form = QFormLayout(container)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(4)
        form.setContentsMargins(8, 8, 8, 8)

        self._detail_widgets: dict[str, QWidget] = {}

        for label_text, db_col in _DETAIL_FIELDS:
            if db_col in _BIT_KEYS:
                w: QWidget = QCheckBox()
                w.setEnabled(False)
            elif db_col in _MULTI_KEYS:
                w = QTextEdit()
                w.setReadOnly(True)
                w.setFixedHeight(60)
            elif db_col == "TYPE":
                w = QComboBox()
                w.setEditable(True)
                w.addItem("")
                w.addItems(fetch_equipment_types())
                w.setEnabled(False)
            else:
                w = QLineEdit()
                w.setReadOnly(True)
            self._detail_widgets[db_col] = w
            form.addRow(QLabel(label_text + ":"), w)

        scroll.setWidget(container)
        outer.addWidget(scroll)
        return gb

    def _build_action_buttons(self) -> QWidget:
        container = QWidget()
        row = QHBoxLayout(container)
        row.setSpacing(8)
        row.setContentsMargins(0, 4, 0, 0)

        can_admin  = current_user.access_level >= AccessLevel.ADMIN
        can_power  = current_user.access_level >= AccessLevel.POWER
        can_create = current_user.access_level >= AccessLevel.CREATE_NEW

        # New — POWER+
        self._new_btn = QPushButton("New")
        self._new_btn.setVisible(can_power)
        self._new_btn.clicked.connect(self._on_new_clicked)
        row.addWidget(self._new_btn)

        # Edit — ADMIN only (full field edit)
        self._edit_btn = QPushButton("Edit")
        self._edit_btn.setVisible(can_admin)
        self._edit_btn.setEnabled(False)
        self._edit_btn.clicked.connect(self._on_edit_clicked)
        row.addWidget(self._edit_btn)

        # Revise — CREATE_NEW+ (new calibration revision)
        self._revise_btn = QPushButton("Revise Cal")
        self._revise_btn.setToolTip("Create a new calibration revision for this equipment")
        self._revise_btn.setVisible(can_create)
        self._revise_btn.setEnabled(False)
        self._revise_btn.clicked.connect(self._on_revise_clicked)
        row.addWidget(self._revise_btn)

        # Obsolete — POWER+
        self._obsolete_btn = QPushButton("Obsolete")
        self._obsolete_btn.setToolTip("Mark this equipment as permanently out of service")
        self._obsolete_btn.setVisible(can_power)
        self._obsolete_btn.setEnabled(False)
        self._obsolete_btn.clicked.connect(self._on_obsolete_clicked)
        row.addWidget(self._obsolete_btn)

        row.addStretch()

        # Save / Cancel — shown only during edit/new/revise
        self._save_btn = QPushButton("Save")
        self._save_btn.setObjectName("save_btn")
        self._save_btn.setVisible(False)
        self._save_btn.clicked.connect(self._on_save_clicked)
        row.addWidget(self._save_btn)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setVisible(False)
        self._cancel_btn.clicked.connect(self._on_cancel_clicked)
        row.addWidget(self._cancel_btn)

        row.addStretch()

        # Select — only in select_mode
        if self._select_mode:
            select_btn = QPushButton("Select")
            select_btn.setObjectName("save_btn")
            select_btn.setToolTip("Use this equipment in the failure report")
            select_btn.clicked.connect(self._on_select_clicked)
            row.addWidget(select_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        row.addWidget(close_btn)

        return container

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_equipment(self):
        type_filter   = self._type_combo.currentText()
        if type_filter == "All Types":
            type_filter = ""
        active_only   = not self._chk_show_inactive.isChecked()
        incl_obsolete = self._chk_show_obsolete.isChecked()

        self._current_data = fetch_all_equipment(
            active_rev_only=active_only,
            include_obsolete=incl_obsolete,
            type_filter=type_filter,
        )
        self._populate_table(self._current_data)
        self._clear_detail()

    def _on_filter_changed(self, *_):
        self._load_equipment()

    def _populate_table(self, rows: list[dict]):
        self._table.setRowCount(0)
        for row_data in rows:
            r = self._table.rowCount()
            self._table.insertRow(r)
            for c, key in enumerate(_LIST_KEYS):
                raw = row_data.get(key)
                if key in _BIT_KEYS:
                    text = "Yes" if raw else "No"
                else:
                    text = "" if raw is None else str(raw)
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(r, c, item)
            # Store the INDEX PK in the first column's UserRole
            idx_pk = row_data.get("INDEX")
            if idx_pk is not None:
                self._table.item(r, 0).setData(Qt.ItemDataRole.UserRole, int(idx_pk))

        self._table.resizeColumnsToContents()

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def _on_selection_changed(self):
        selected = self._table.selectedItems()
        if not selected:
            self._current_row_index = None
            self._clear_detail()
            self._set_row_buttons_enabled(False)
            return

        row = self._table.currentRow()
        item = self._table.item(row, 0)
        self._current_row_index = (
            item.data(Qt.ItemDataRole.UserRole) if item else None
        )

        # Find matching row data
        row_data = None
        for d in self._current_data:
            if d.get("INDEX") == self._current_row_index:
                row_data = d
                break

        if row_data:
            self._populate_detail(row_data)
        self._set_row_buttons_enabled(True)

    def _on_table_double_clicked(self, _index):
        if self._select_mode:
            self._on_select_clicked()

    def _set_row_buttons_enabled(self, enabled: bool):
        for btn in (self._edit_btn, self._revise_btn, self._obsolete_btn):
            btn.setEnabled(enabled)

    # ------------------------------------------------------------------
    # Detail pane
    # ------------------------------------------------------------------

    def _populate_detail(self, row_data: dict):
        for db_col, widget in self._detail_widgets.items():
            raw = row_data.get(db_col)
            if isinstance(widget, QCheckBox):
                widget.setChecked(bool(raw))
            elif isinstance(widget, QTextEdit):
                widget.setPlainText("" if raw is None else str(raw))
            elif isinstance(widget, QComboBox):
                text = "" if raw is None else str(raw)
                idx  = widget.findText(text)
                widget.setCurrentIndex(max(0, idx))
            else:
                widget.setText("" if raw is None else str(raw))

    def _clear_detail(self):
        for widget in self._detail_widgets.values():
            if isinstance(widget, QCheckBox):
                widget.setChecked(False)
            elif isinstance(widget, QTextEdit):
                widget.clear()
            elif isinstance(widget, QComboBox):
                widget.setCurrentIndex(0)
            else:
                widget.clear()

    # ------------------------------------------------------------------
    # Edit mode helpers
    # ------------------------------------------------------------------

    def _set_detail_editable(self, editable: bool, cal_only: bool = False):
        """
        Toggle detail pane editability.
        cal_only=True: only cal date fields editable (Revise Cal mode).
        """
        cal_fields = {"LAST CAL", "NEXT CAL"}
        for db_col, widget in self._detail_widgets.items():
            if cal_only:
                should_edit = db_col in cal_fields
            else:
                should_edit = editable
            if isinstance(widget, QCheckBox):
                widget.setEnabled(should_edit)
            elif isinstance(widget, QTextEdit):
                widget.setReadOnly(not should_edit)
            elif isinstance(widget, QComboBox):
                widget.setEnabled(should_edit)
            else:
                widget.setReadOnly(not should_edit)

        # ID and REV are always read-only (system-managed)
        for key in ("ID", "REV", "ACTIVE REV", "OBSOLETE"):
            w = self._detail_widgets.get(key)
            if w:
                if isinstance(w, QCheckBox):
                    w.setEnabled(False)
                elif isinstance(w, QLineEdit):
                    w.setReadOnly(True)

    def _set_edit_ui(self, editing: bool):
        self._editing = editing
        self._save_btn.setVisible(editing)
        self._cancel_btn.setVisible(editing)
        self._new_btn.setEnabled(not editing)
        self._edit_btn.setEnabled(not editing and self._current_row_index is not None)
        self._revise_btn.setEnabled(not editing and self._current_row_index is not None)
        self._obsolete_btn.setEnabled(not editing and self._current_row_index is not None)

    def _collect_detail_fields(self) -> dict:
        fields: dict = {}
        for db_col, widget in self._detail_widgets.items():
            if isinstance(widget, QCheckBox):
                fields[db_col] = 1 if widget.isChecked() else 0
            elif isinstance(widget, QTextEdit):
                fields[db_col] = widget.toPlainText().strip() or None
            elif isinstance(widget, QComboBox):
                fields[db_col] = widget.currentText().strip() or None
            else:
                fields[db_col] = widget.text().strip() or None
        return fields

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def _on_new_clicked(self):
        self._new_mode  = True
        self._revise_mode = False
        self._clear_detail()
        self._set_detail_editable(True)
        self._set_edit_ui(True)

        # Assign next ID and default values
        next_id = get_max_equipment_id() + 1
        self._detail_widgets["ID"].setText(str(next_id))
        self._detail_widgets["REV"].setText("0")
        cal_req_w = self._detail_widgets.get("CAL REQ")
        if isinstance(cal_req_w, QCheckBox):
            cal_req_w.setChecked(True)
        active_w = self._detail_widgets.get("ACTIVE REV")
        if isinstance(active_w, QCheckBox):
            active_w.setChecked(True)

    def _on_edit_clicked(self):
        if self._current_row_index is None:
            return
        self._new_mode    = False
        self._revise_mode = False
        self._set_detail_editable(True)
        self._set_edit_ui(True)

    def _on_revise_clicked(self):
        """
        Revise calibration — creates a new row with updated cal dates,
        marks old row inactive.  Mirrors VB ReviseCalDevice state.
        """
        if self._current_row_index is None:
            return
        self._new_mode    = False
        self._revise_mode = True
        self._set_detail_editable(True, cal_only=True)
        self._set_edit_ui(True)

        # Clear the cal date fields so user must enter new dates
        for key in ("LAST CAL", "NEXT CAL"):
            w = self._detail_widgets.get(key)
            if isinstance(w, QLineEdit):
                w.clear()

        # Pre-fill today as Last Cal
        today_str = _date.today().strftime("%Y-%m-%d")
        last_cal_w = self._detail_widgets.get("LAST CAL")
        if isinstance(last_cal_w, QLineEdit):
            last_cal_w.setText(today_str)

    def _on_obsolete_clicked(self):
        if self._current_row_index is None:
            return
        reply = QMessageBox.question(
            self,
            "Obsolete Equipment",
            "Mark this equipment as <b>obsolete (out of service)</b>?\n\n"
            "The record will be hidden by default but not deleted.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        ok = obsolete_equipment(self._current_row_index)
        if ok:
            QMessageBox.information(self, "Obsoleted", "Equipment marked as obsolete.")
            self._load_equipment()
        else:
            QMessageBox.critical(self, "Error", "Could not mark equipment as obsolete.")

    def _on_save_clicked(self):
        fields = self._collect_detail_fields()

        if self._new_mode:
            # Remove system-managed fields that should come from form
            new_index = create_equipment(fields)
            if new_index is not None:
                QMessageBox.information(
                    self, "Created",
                    f"Equipment created successfully (Index: {new_index})."
                )
                self._new_mode = False
                self._set_edit_ui(False)
                self._set_detail_editable(False)
                self._load_equipment()
            else:
                QMessageBox.critical(self, "Error", "Could not create equipment.")

        elif self._revise_mode:
            # Build new revision fields from current detail + updated cal dates
            new_fields = dict(fields)
            # Bump revision number
            try:
                current_rev = int(self._detail_widgets["REV"].text() or "0")
            except ValueError:
                current_rev = 0
            new_fields["REV"] = str(current_rev + 1)
            new_fields["ACTIVE REV"] = 1

            new_index = revise_equipment(self._current_row_index, new_fields)
            if new_index is not None:
                QMessageBox.information(
                    self, "Revised",
                    f"New calibration revision created (Index: {new_index})."
                )
                self._revise_mode = False
                self._set_edit_ui(False)
                self._set_detail_editable(False)
                self._load_equipment()
            else:
                QMessageBox.critical(self, "Error", "Could not create revision.")

        else:
            # Standard edit save
            ok = update_equipment(self._current_row_index, fields)
            if ok:
                QMessageBox.information(self, "Saved", "Equipment updated.")
                self._set_edit_ui(False)
                self._set_detail_editable(False)
                self._load_equipment()
            else:
                QMessageBox.critical(self, "Error", "Could not save equipment.")

    def _on_cancel_clicked(self):
        self._new_mode    = False
        self._revise_mode = False
        self._set_edit_ui(False)
        self._set_detail_editable(False)
        # Re-populate from current selection if any
        if self._current_row_index is not None:
            for d in self._current_data:
                if d.get("INDEX") == self._current_row_index:
                    self._populate_detail(d)
                    break
        else:
            self._clear_detail()

    def _on_select_clicked(self):
        """Return selected equipment ID to caller (select_mode only)."""
        if self._current_row_index is None:
            QMessageBox.warning(self, "No Selection", "Please select a piece of equipment.")
            return
        # Find the equipment ID (not INDEX) for the selected row
        for d in self._current_data:
            if d.get("INDEX") == self._current_row_index:
                self.selected_equipment_id = d.get("ID")
                break
        self.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and not self._editing:
            self.reject()
        else:
            super().keyPressEvent(event)


# ---------------------------------------------------------------------------
# Convenience helper
# ---------------------------------------------------------------------------

def open_test_equipment(parent=None, select_mode: bool = False) -> TestEquipmentDialog:
    """Create and exec a TestEquipmentDialog; return the dialog instance."""
    dlg = TestEquipmentDialog(parent=parent, select_mode=select_mode)
    dlg.exec()
    return dlg
