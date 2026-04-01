"""
Manage Users dialog — ADMIN only.

Lets admins:
  • View all user accounts (active and inactive)
  • Add a new user (blank password, forced reset on first login)
  • Edit name / access level / email on an existing user
  • Activate or deactivate an account (soft-disable, never hard-delete)
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from auth.session import AccessLevel, current_user
from db.lookup_queries import (
    create_user,
    fetch_all_users,
    set_user_active,
    update_user,
)

# Access level value → display name (mirrors AccessLevel enum)
_LEVEL_LABELS = {
    0: "No Access",
    1: "Read Only",
    2: "Create New",
    3: "CR Edit",
    4: "Power",
    5: "Approver",
    6: "Admin",
}
_LEVEL_VALUES = {v: k for k, v in _LEVEL_LABELS.items()}

_COL_ID    = 0
_COL_USER  = 1
_COL_FIRST = 2
_COL_LAST  = 3
_COL_LEVEL = 4
_COL_EMAIL = 5
_COL_ACTIVE = 6

_HEADERS = ["ID", "Username", "First Name", "Last Name", "Access Level", "Email", "Active"]


class _UserEditorDialog(QDialog):
    """Add or edit a single user."""

    def __init__(self, row: dict | None = None, parent=None):
        super().__init__(parent)
        self._row = row
        is_new = row is None
        self.setWindowTitle("Add User" if is_new else "Edit User")
        self.setMinimumWidth(380)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )

        form = QFormLayout(self)
        form.setSpacing(10)
        form.setContentsMargins(16, 16, 16, 16)

        self._username = QLineEdit()
        self._username.setPlaceholderText("domain\\username or short login")
        if not is_new:
            self._username.setText(str(row.get("username", "")))
            self._username.setReadOnly(True)  # username is the identity — don't rename
        form.addRow("Username:*", self._username)

        self._first = QLineEdit(str(row.get("FirstName", "")) if row else "")
        form.addRow("First Name:*", self._first)

        self._last = QLineEdit(str(row.get("LastName", "")) if row else "")
        form.addRow("Last Name:*", self._last)

        self._level_combo = QComboBox()
        for val, label in sorted(_LEVEL_LABELS.items()):
            self._level_combo.addItem(label, userData=val)
        if row:
            current_level = int(row.get("AccessLevel", 1))
            idx = self._level_combo.findData(current_level)
            if idx >= 0:
                self._level_combo.setCurrentIndex(idx)
        form.addRow("Access Level:*", self._level_combo)

        self._email = QLineEdit(str(row.get("email", "")) if row else "")
        self._email.setPlaceholderText("optional")
        form.addRow("Email:", self._email)

        if is_new:
            note = QLabel("Password will be blank — user must set it on first login.")
            note.setStyleSheet("color: #777; font-size: 8pt;")
            note.setWordWrap(True)
            form.addRow("", note)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        ok_btn = QPushButton("Save")
        ok_btn.setObjectName("save_btn")
        ok_btn.setFixedWidth(80)
        ok_btn.clicked.connect(self._on_save)
        btn_row.addWidget(ok_btn)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("cancel_btn")
        cancel_btn.setFixedWidth(80)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        form.addRow("", btn_row)

    def _on_save(self):
        username = self._username.text().strip()
        first    = self._first.text().strip()
        last     = self._last.text().strip()
        level    = self._level_combo.currentData()
        email    = self._email.text().strip()

        if not username or not first or not last:
            QMessageBox.warning(self, "Required Fields",
                                "Username, First Name, and Last Name are required.")
            return

        if self._row is None:
            ok = create_user(username, first, last, level, email)
            if not ok:
                QMessageBox.critical(self, "Error",
                                     "Could not create user. Username may already exist.")
                return
        else:
            ok = update_user(int(self._row["ID"]), first, last, level, email)
            if not ok:
                QMessageBox.critical(self, "Error", "Could not update user.")
                return

        self.accept()


class ManageUsersDialog(QDialog):
    """Full user management table — ADMIN only."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manage Users")
        self.resize(820, 540)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # ── Header ────────────────────────────────────────────────
        hdr = QLabel("User Accounts")
        f = QFont()
        f.setPointSize(11)
        f.setBold(True)
        hdr.setFont(f)
        root.addWidget(hdr)

        # ── Show inactive toggle ───────────────────────────────────
        toggle_row = QHBoxLayout()
        self._show_inactive = QCheckBox("Show inactive accounts")
        self._show_inactive.stateChanged.connect(self._load)
        toggle_row.addWidget(self._show_inactive)
        toggle_row.addStretch()
        root.addLayout(toggle_row)

        # ── Table ─────────────────────────────────────────────────
        self._table = QTableWidget(0, len(_HEADERS))
        self._table.setHorizontalHeaderLabels(_HEADERS)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setColumnWidth(_COL_ID,    40)
        self._table.setColumnWidth(_COL_USER,  110)
        self._table.setColumnWidth(_COL_FIRST,  90)
        self._table.setColumnWidth(_COL_LAST,   110)
        self._table.setColumnWidth(_COL_LEVEL,  100)
        self._table.setColumnWidth(_COL_EMAIL,  160)
        self._table.setColumnWidth(_COL_ACTIVE,  55)
        self._table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        root.addWidget(self._table, stretch=1)

        # ── Action buttons ────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._add_btn = QPushButton("+ Add User")
        self._add_btn.setObjectName("new_report_btn")
        self._add_btn.clicked.connect(self._on_add)
        btn_row.addWidget(self._add_btn)

        self._edit_btn = QPushButton("Edit")
        self._edit_btn.setObjectName("outline_btn")
        self._edit_btn.setEnabled(False)
        self._edit_btn.clicked.connect(self._on_edit)
        btn_row.addWidget(self._edit_btn)

        self._toggle_btn = QPushButton("Deactivate")
        self._toggle_btn.setObjectName("outline_btn")
        self._toggle_btn.setEnabled(False)
        self._toggle_btn.clicked.connect(self._on_toggle_active)
        btn_row.addWidget(self._toggle_btn)

        btn_row.addStretch()

        close_btn = QPushButton("Close")
        close_btn.setObjectName("outline_btn")
        close_btn.setFixedWidth(80)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)

        root.addLayout(btn_row)

        self._users: list[dict] = []
        self._load()

    # ------------------------------------------------------------------

    def _load(self):
        self._users = fetch_all_users()
        show_inactive = self._show_inactive.isChecked()

        self._table.setRowCount(0)
        for row in self._users:
            active = bool(row.get("Active", False))
            if not active and not show_inactive:
                continue

            r = self._table.rowCount()
            self._table.insertRow(r)

            def _item(val):
                it = QTableWidgetItem("" if val is None else str(val))
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                return it

            level_val = int(row.get("AccessLevel", 1))
            level_str = _LEVEL_LABELS.get(level_val, str(level_val))

            self._table.setItem(r, _COL_ID,    _item(row.get("ID")))
            self._table.setItem(r, _COL_USER,  _item(row.get("username")))
            self._table.setItem(r, _COL_FIRST, _item(row.get("FirstName")))
            self._table.setItem(r, _COL_LAST,  _item(row.get("LastName")))
            self._table.setItem(r, _COL_LEVEL, _item(level_str))
            self._table.setItem(r, _COL_EMAIL, _item(row.get("email")))
            self._table.setItem(r, _COL_ACTIVE, _item("Yes" if active else "No"))

            # Dim inactive rows
            if not active:
                for col in range(len(_HEADERS)):
                    item = self._table.item(r, col)
                    if item:
                        item.setForeground(QColor("#aaa"))

        self._on_selection_changed()

    def _selected_user(self) -> dict | None:
        rows = self._table.selectedItems()
        if not rows:
            return None
        row_idx = self._table.currentRow()
        user_id = int(self._table.item(row_idx, _COL_ID).text())
        return next((u for u in self._users if u.get("ID") == user_id), None)

    def _on_selection_changed(self):
        user = self._selected_user()
        self._edit_btn.setEnabled(user is not None)
        self._toggle_btn.setEnabled(user is not None)
        if user is not None:
            is_active = bool(user.get("Active", False))
            self._toggle_btn.setText("Deactivate" if is_active else "Activate")

    def _on_add(self):
        dlg = _UserEditorDialog(parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._load()

    def _on_edit(self):
        user = self._selected_user()
        if user is None:
            return
        dlg = _UserEditorDialog(row=user, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._load()

    def _on_toggle_active(self):
        user = self._selected_user()
        if user is None:
            return
        is_active  = bool(user.get("Active", False))
        name       = f"{user.get('FirstName', '')} {user.get('LastName', '')}".strip()
        action     = "deactivate" if is_active else "activate"

        if QMessageBox.question(
            self, f"{action.capitalize()} User",
            f"{action.capitalize()} account for <b>{name}</b> ({user.get('username')})?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        ) != QMessageBox.StandardButton.Yes:
            return

        if set_user_active(int(user["ID"]), not is_active):
            self._load()
        else:
            QMessageBox.critical(self, "Error", f"Could not {action} user.")


def open_manage_users(parent=None):
    """Open the Manage Users dialog — enforces ADMIN gate."""
    if current_user.access_level < AccessLevel.ADMIN:
        QMessageBox.warning(parent, "Access Denied",
                            "User management requires ADMIN access.")
        return
    dlg = ManageUsersDialog(parent=parent)
    dlg.exec()
