"""
Change password dialog — mirrors frmChangePassWord.vb.

Password rules (matching VB's ValidatePassword call with bSuppressMessage=False, min=8,
upper=1, lower=1, number=1, special=1):
  - Minimum 8 characters
  - At least 1 uppercase letter
  - At least 1 lowercase letter
  - At least 1 digit
  - At least 1 special character
  - No 3+ consecutive identical characters

A strength bar gives live feedback as the user types (matching pbPasswordStrength).
"""

import re

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from db.lookup_queries import fetch_user_by_username, update_user_password


# ---------------------------------------------------------------------------
# Password validation (mirrors VB ValidatePassword + hasConsecutiveCharacters)
# ---------------------------------------------------------------------------

_RE_UPPER   = re.compile(r"[A-Z]")
_RE_LOWER   = re.compile(r"[a-z]")
_RE_DIGIT   = re.compile(r"[0-9]")
_RE_SPECIAL = re.compile(r"[^a-zA-Z0-9]")

MIN_LENGTH   = 8
MAX_CONSEC   = 3  # max consecutive identical chars before flagging


def _has_consecutive(pwd: str, n: int = MAX_CONSEC) -> bool:
    """Return True if pwd contains n or more consecutive identical characters."""
    for i in range(len(pwd) - n + 1):
        if len(set(pwd[i:i + n])) == 1:
            return True
    return False


def _score(pwd: str) -> int:
    """
    Return an integer strength score (0–7) matching VB's ComputeScore(iScore).
    Score bits:
      MINIMUM_LENGTH_MET          = 1
      EXCEEDS_MINIMUM_LENGTH      = 2
      HAS_LOWER_CASE              = 4
      HAS_NUMBER                  = 8  → mapped down to keep max=7
      HAS_UPPER_CASE              = 16 → ...
      HAS_NON_ALPHA_NUMERIC       = 32 → ...
      MAX_CONSEQ_NOT_EXCEEDED     = 64 → ...
    We return a 0-7 level for the progress bar.
    """
    if not pwd:
        return 0
    level = 0
    if len(pwd) >= MIN_LENGTH:
        level += 1
    if len(pwd) > MIN_LENGTH:
        level += 1
    if _RE_LOWER.search(pwd):
        level += 1
    if _RE_DIGIT.search(pwd):
        level += 1
    if _RE_UPPER.search(pwd):
        level += 1
    if _RE_SPECIAL.search(pwd):
        level += 1
    if not _has_consecutive(pwd):
        level += 1
    return level


def _validate(pwd: str) -> tuple[bool, str]:
    """Return (is_valid, error_message)."""
    if len(pwd) < MIN_LENGTH:
        return False, f"Password must be at least {MIN_LENGTH} characters."
    if not _RE_UPPER.search(pwd):
        return False, "Password must contain at least 1 uppercase letter."
    if not _RE_LOWER.search(pwd):
        return False, "Password must contain at least 1 lowercase letter."
    if not _RE_DIGIT.search(pwd):
        return False, "Password must contain at least 1 digit."
    if not _RE_SPECIAL.search(pwd):
        return False, "Password must contain at least 1 special character."
    if _has_consecutive(pwd):
        return False, f"Password must not contain {MAX_CONSEC} or more consecutive identical characters."
    return True, ""


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------

_STRENGTH_COLORS = [
    "#c0392b",  # 0 — blank / invalid
    "#c0392b",  # 1 — very weak
    "#e67e22",  # 2 — weak
    "#f1c40f",  # 3 — fair
    "#f1c40f",  # 4 — fair+
    "#27ae60",  # 5 — good
    "#27ae60",  # 6 — strong
    "#1e8449",  # 7 — very strong
]


class ChangePasswordDialog(QDialog):
    """
    Prompts the user to change their internal database password.
    Accepts username as constructor argument so it works both from the
    login flow (PASSWORDISRESET) and from a logged-in settings menu.
    """

    def __init__(self, username: str, parent=None):
        super().__init__(parent)
        self._username = username
        self.setWindowTitle("Change Password")
        self.setFixedWidth(400)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(18, 18, 18, 18)

        info = QLabel(
            f"Changing password for <b>{self._username}</b>.<br>"
            "Password must be at least 8 characters and contain:<br>"
            "1 uppercase, 1 lowercase, 1 digit, and 1 special character."
        )
        info.setWordWrap(True)
        root.addWidget(info)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(sep)

        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)

        self._old_pw = QLineEdit()
        self._old_pw.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Current password:", self._old_pw)

        self._new_pw = QLineEdit()
        self._new_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self._new_pw.textChanged.connect(self._on_password_changed)
        form.addRow("New password:", self._new_pw)

        self._repeat_pw = QLineEdit()
        self._repeat_pw.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Repeat new password:", self._repeat_pw)

        root.addLayout(form)

        # Strength bar (matches pbPasswordStrength)
        strength_row = QHBoxLayout()
        strength_row.addWidget(QLabel("Strength:"))
        self._strength_bar = QProgressBar()
        self._strength_bar.setRange(0, 7)
        self._strength_bar.setValue(0)
        self._strength_bar.setTextVisible(False)
        self._strength_bar.setFixedHeight(12)
        strength_row.addWidget(self._strength_bar, stretch=1)
        self._strength_label = QLabel("")
        self._strength_label.setFixedWidth(80)
        strength_row.addWidget(self._strength_label)
        root.addLayout(strength_row)

        # Show password checkbox (matches CheckBox1)
        self._show_pw = QCheckBox("Show passwords")
        self._show_pw.stateChanged.connect(self._toggle_echo)
        root.addWidget(self._show_pw)

        # Error label
        self._error = QLabel("")
        self._error.setWordWrap(True)
        self._error.setStyleSheet("color: #c0392b;")
        root.addWidget(self._error)

        # Buttons
        btn_row = QHBoxLayout()
        ok_btn = QPushButton("Change Password")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._on_ok)
        btn_row.addWidget(ok_btn)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        root.addLayout(btn_row)

    # ------------------------------------------------------------------

    def _toggle_echo(self, state: int):
        mode = (
            QLineEdit.EchoMode.Normal
            if state == Qt.CheckState.Checked.value
            else QLineEdit.EchoMode.Password
        )
        for w in (self._old_pw, self._new_pw, self._repeat_pw):
            w.setEchoMode(mode)

    def _on_password_changed(self, text: str):
        s = _score(text)
        self._strength_bar.setValue(s)
        color = _STRENGTH_COLORS[min(s, 7)]
        self._strength_bar.setStyleSheet(
            f"QProgressBar::chunk {{ background-color: {color}; }}"
        )
        labels = ["", "Very Weak", "Weak", "Fair", "Fair", "Good", "Strong", "Very Strong"]
        self._strength_label.setText(labels[min(s, 7)])
        self._strength_label.setStyleSheet(f"color: {color};")

    def _on_ok(self):
        old_pw   = self._old_pw.text()
        new_pw   = self._new_pw.text()
        repeat   = self._repeat_pw.text()

        # Verify old password against DB
        user_row = fetch_user_by_username(self._username)
        if user_row is None:
            self._error.setText("User not found.")
            return

        db_pw = str(user_row.get("PASSWORD", "") or "").strip()
        if old_pw.strip() != db_pw:
            self._error.setText("Current password is incorrect.")
            return

        if new_pw != repeat:
            self._error.setText("New password and repeat must match.")
            return

        valid, msg = _validate(new_pw)
        if not valid:
            self._error.setText(msg)
            return

        user_id = int(user_row.get("ID", 0) or 0)
        if update_user_password(user_id, new_pw):
            self.accept()
        else:
            self._error.setText("Database error — password not updated. Try again.")
