"""
Lookup Table Admin dialog — mirrors frmCustomizeDropDowns.vb.
ADMIN-only. Opens from the dashboard "Admin" button.

Provides full CRUD for all METER_SPECS lookup tables:
  AMR, Meter, Base, Form, Level, Test Type, Test Standards,
  Tested By, Approver Type.

Access pattern (matching VB tsmOptionsManageDropdown):
  Only eAccessState.ADMIN users may open or modify this dialog.
  All non-admin callers receive an access-denied message.

Soft-delete pattern:
  Most tables have an ACTIVE (BIT) column.  "Deactivate" sets ACTIVE=0
  rather than hard-deleting, so existing failure reports that reference
  the value still display correctly.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from auth.session import AccessLevel, current_user
from db.lookup_admin_queries import (
    add_lookup_row,
    fetch_lookup_rows,
    set_lookup_active,
    update_lookup_row,
)

# ---------------------------------------------------------------------------
# Table definitions
# Each entry:
#   label      — tab label shown to user
#   table      — exact METER_SPECS table name (bracket-safe)
#   cols       — editable columns in display order (ID is always shown but not editable)
#   has_active — whether the table has an ACTIVE (BIT) column
# ---------------------------------------------------------------------------

_TABLES: list[dict] = [
    {
        "label":      "AMR",
        "table":      "AMR",
        "cols":       ["AMR", "AMR_MANUFACTURER", "AMR_TYPE",
                       "AMR_SUBTYPE", "AMR_SUBTYPEII", "AMR_SUBTYPEIII"],
        "has_active": True,
    },
    {
        "label":      "Meter",
        "table":      "METER",
        "cols":       ["METER", "METER_MANUFACTURER", "METER_TYPE",
                       "METER_SUBTYPE", "METER_SUBTYPEII"],
        "has_active": True,
    },
    {
        "label":      "Base",
        "table":      "BASE",
        "cols":       ["BASE"],
        "has_active": True,
    },
    {
        "label":      "Form",
        "table":      "FORM",
        "cols":       ["FORM", "METER_BASE"],
        "has_active": True,
    },
    {
        "label":      "Test Level",
        "table":      "LEVEL",
        "cols":       ["LEVEL"],
        "has_active": True,
    },
    {
        "label":      "Test Type",
        "table":      "TEST_TYPE",
        "cols":       ["TEST_TYPE", "TEST_TYPE_NUMBER"],
        "has_active": True,
    },
    {
        "label":      "Test Standards",
        "table":      "TEST STANDARDS",
        "cols":       ["TEST", "TEST_TYPE", "TAGS"],
        "has_active": True,
    },
    {
        "label":      "Tested By",
        "table":      "TESTED BY",
        "cols":       ["TESTED BY"],
        "has_active": True,
    },
    {
        "label":      "Approver Type",
        "table":      "APPROVER_TYPE",
        "cols":       ["DISCIPLINE"],
        "has_active": False,
    },
]


# ---------------------------------------------------------------------------
# Row editor dialog (Add / Edit)
# ---------------------------------------------------------------------------

class _RowEditorDialog(QDialog):
    """
    Generic single-row editor.  Builds a QFormLayout from the column list
    and returns collected values via self.values dict on accept.
    """

    def __init__(self, table_def: dict, initial: dict | None = None, parent=None):
        super().__init__(parent)
        self.values: dict = {}
        cols       = table_def["cols"]
        has_active = table_def["has_active"]
        is_edit    = initial is not None

        self.setWindowTitle("Edit Row" if is_edit else "Add Row")
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        self.setMinimumWidth(420)

        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(16, 16, 16, 16)

        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)

        self._widgets: dict[str, QWidget] = {}

        for col in cols:
            w = QLineEdit()
            if is_edit and initial:
                raw = initial.get(col)
                w.setText("" if raw is None else str(raw))
            self._widgets[col] = w
            form.addRow(QLabel(col.replace("_", " ").title() + ":"), w)

        if has_active:
            chk = QCheckBox("Active")
            chk.setChecked(True if not is_edit else bool(initial.get("ACTIVE", True)))
            self._widgets["ACTIVE"] = chk
            form.addRow(QLabel("Active:"), chk)

        root.addLayout(form)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    def _on_accept(self):
        self.values = {}
        for col, widget in self._widgets.items():
            if isinstance(widget, QCheckBox):
                self.values[col] = 1 if widget.isChecked() else 0
            else:
                self.values[col] = widget.text().strip() or None
        self.accept()


# ---------------------------------------------------------------------------
# Single-table tab widget
# ---------------------------------------------------------------------------

class _LookupTableTab(QWidget):
    """
    One tab managing a single METER_SPECS lookup table.
    Displays all rows in a read-only table; buttons add/edit/toggle active.
    """

    def __init__(self, table_def: dict, parent=None):
        super().__init__(parent)
        self._def = table_def
        self._rows: list[dict] = []
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(6)
        root.setContentsMargins(8, 8, 8, 8)

        # Table
        cols = ["ID"] + self._def["cols"]
        if self._def["has_active"]:
            cols.append("ACTIVE")

        self._table = QTableWidget(0, len(cols))
        self._table.setHorizontalHeaderLabels(
            [c.replace("_", " ").title() for c in cols]
        )
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        self._col_keys = cols
        root.addWidget(self._table, stretch=1)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        add_btn = QPushButton("Add")
        add_btn.setFixedWidth(80)
        add_btn.clicked.connect(self._on_add)
        btn_row.addWidget(add_btn)

        self._edit_btn = QPushButton("Edit")
        self._edit_btn.setFixedWidth(80)
        self._edit_btn.setEnabled(False)
        self._edit_btn.clicked.connect(self._on_edit)
        btn_row.addWidget(self._edit_btn)

        if self._def["has_active"]:
            self._toggle_btn = QPushButton("Toggle Active")
            self._toggle_btn.setEnabled(False)
            self._toggle_btn.setToolTip(
                "Activate / deactivate selected row (soft-delete)"
            )
            self._toggle_btn.clicked.connect(self._on_toggle_active)
            btn_row.addWidget(self._toggle_btn)
        else:
            self._toggle_btn = None

        btn_row.addStretch()

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setFixedWidth(80)
        refresh_btn.clicked.connect(self.refresh)
        btn_row.addWidget(refresh_btn)

        root.addLayout(btn_row)

        self._table.itemSelectionChanged.connect(self._on_selection_changed)

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def refresh(self):
        self._rows = fetch_lookup_rows(self._def["table"])
        self._populate_table()
        self._set_buttons_enabled(False)

    def _populate_table(self):
        self._table.setRowCount(0)
        for row_data in self._rows:
            r = self._table.rowCount()
            self._table.insertRow(r)
            for c, key in enumerate(self._col_keys):
                raw = row_data.get(key)
                if key == "ACTIVE":
                    text = "Yes" if raw else "No"
                else:
                    text = "" if raw is None else str(raw)
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                # Gray out inactive rows
                if self._def["has_active"] and not row_data.get("ACTIVE", True):
                    from PyQt6.QtGui import QColor
                    item.setForeground(QColor("#999"))
                self._table.setItem(r, c, item)
            # Store row ID in column 0 UserRole
            row_id = row_data.get("ID")
            if row_id is not None:
                self._table.item(r, 0).setData(
                    Qt.ItemDataRole.UserRole, int(row_id)
                )
        self._table.resizeColumnsToContents()

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def _on_selection_changed(self):
        has_sel = bool(self._table.selectedItems())
        self._set_buttons_enabled(has_sel)

    def _set_buttons_enabled(self, enabled: bool):
        self._edit_btn.setEnabled(enabled)
        if self._toggle_btn:
            self._toggle_btn.setEnabled(enabled)

    def _selected_row_data(self) -> dict | None:
        sel = self._table.selectedItems()
        if not sel:
            return None
        row = self._table.currentRow()
        item = self._table.item(row, 0)
        row_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        for d in self._rows:
            if d.get("ID") == row_id:
                return d
        return None

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_add(self):
        dlg = _RowEditorDialog(self._def, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        ok = add_lookup_row(self._def["table"], dlg.values)
        if ok:
            self.refresh()
        else:
            QMessageBox.critical(self, "Error", "Could not add row — check the console for details.")

    def _on_edit(self):
        row_data = self._selected_row_data()
        if row_data is None:
            return
        dlg = _RowEditorDialog(self._def, initial=row_data, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        row_id = row_data["ID"]
        # Separate out ACTIVE from the rest (has its own endpoint)
        fields = {k: v for k, v in dlg.values.items() if k != "ACTIVE"}
        ok = update_lookup_row(self._def["table"], row_id, fields)
        if ok and self._def["has_active"] and "ACTIVE" in dlg.values:
            set_lookup_active(self._def["table"], row_id, bool(dlg.values["ACTIVE"]))
        if ok:
            self.refresh()
        else:
            QMessageBox.critical(self, "Error", "Could not save changes.")

    def _on_toggle_active(self):
        row_data = self._selected_row_data()
        if row_data is None:
            return
        row_id     = row_data["ID"]
        is_active  = bool(row_data.get("ACTIVE", True))
        action     = "deactivate" if is_active else "activate"
        value_text = row_data.get(self._def["cols"][0], f"ID {row_id}")

        reply = QMessageBox.question(
            self,
            "Toggle Active",
            f"{action.capitalize()} <b>{value_text}</b>?\n\n"
            f"{'Deactivating hides this value from new report dropdowns '
               'but does not affect existing records.'
               if is_active else
               'Activating will make this value selectable again.'}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        ok = set_lookup_active(self._def["table"], row_id, not is_active)
        if ok:
            self.refresh()
        else:
            QMessageBox.critical(self, "Error", f"Could not {action} row.")


# ---------------------------------------------------------------------------
# Main dialog
# ---------------------------------------------------------------------------

class ManageLookupsDialog(QDialog):
    """
    ADMIN-only dialog for editing all METER_SPECS lookup tables.
    Mirrors frmCustomizeDropDowns.vb with full Add / Edit / Deactivate support.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Lookup Table Admin")
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        self.resize(900, 600)
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(12, 12, 12, 12)

        # Header
        title = QLabel("Lookup Table Admin")
        f = QFont()
        f.setPointSize(13)
        f.setBold(True)
        title.setFont(f)
        root.addWidget(title)

        sub = QLabel(
            "Changes affect dropdown options for all new failure reports.  "
            "Deactivating a value hides it from dropdowns but does not remove "
            "it from existing records."
        )
        sub.setWordWrap(True)
        sub.setStyleSheet("color: #666; font-size: 9pt;")
        root.addWidget(sub)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(sep)

        # Tabs — one per lookup table
        tabs = QTabWidget()
        for tdef in _TABLES:
            tab = _LookupTableTab(tdef)
            tabs.addTab(tab, tdef["label"])
        root.addWidget(tabs, stretch=1)

        # Close button
        close_row = QHBoxLayout()
        close_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(80)
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        root.addLayout(close_row)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.accept()
        else:
            super().keyPressEvent(event)


# ---------------------------------------------------------------------------
# Convenience helper
# ---------------------------------------------------------------------------

def open_manage_lookups(parent=None):
    """
    Open the lookup admin dialog.  Enforces ADMIN access gate.
    """
    if current_user.access_level < AccessLevel.ADMIN:
        QMessageBox.warning(
            parent,
            "Access Denied",
            "Only ADMIN users can manage lookup tables.",
        )
        return
    dlg = ManageLookupsDialog(parent=parent)
    dlg.exec()
