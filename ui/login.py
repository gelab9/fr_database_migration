"""
Login dialog — mirrors frmLogin.vb.

Authentication flow (exact match to VB):
  1. User enters username + password.
  2. Try to validate against Active Directory (domain am.bm.net).
     If AD succeeds → domain_validated = True.
  3. Query USERS table in METER_SPECS for matching username.
     If not found or multiple rows → show error.
  4. If domain_validated OR password matches USERS.PASSWORD:
       a. Check USERS.ACTIVE.
       b. Check USERS.PASSWORDISRESET → prompt change if set.
       c. If USERS.ACCESSLEVEL == APPROVER (5), look up APPROVERS table
          for APPROVER_TYPE_ID to set discipline.
       d. Set current_user via auth.session.set_current_user().
  5. "Browse (Read Only)" button skips auth and sets READ_ONLY access.

AD validation is attempted but failures are silently swallowed — the
internal password is always the fallback (matching VB behaviour).
"""

import getpass

from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QFont, QKeySequence
from PyQt6.QtWidgets import (
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from auth.session import (
    AccessLevel,
    ApproverDiscipline,
    User,
    set_current_user,
)
from db.lookup_queries import (
    fetch_approvers_by_user_id_all,
    fetch_user_by_username,
)

SETTINGS_ORG = "GELab"
SETTINGS_APP = "FRDatabase"
SETTINGS_USERNAME = "login/username"


def _try_ad_validate(username: str, password: str) -> bool:
    """
    Attempt Windows AD validation via LDAP (domain am.bm.net).
    Returns True on success, False on any failure.
    Mirrors ValidateUserOnActiveDomainServer() in frmLogin.vb.
    """
    try:
        import ldap3
        server = ldap3.Server("am.bm.net", get_info=ldap3.ALL)
        conn = ldap3.Connection(
            server,
            user=f"am\\{username}",
            password=password,
            authentication=ldap3.NTLM,
            auto_bind=True,
        )
        conn.unbind()
        return True
    except Exception:
        pass

    # Fallback: try pywin32 / win32security if available (Windows only)
    try:
        import win32security
        token = win32security.LogonUser(
            username,
            "am.bm.net",
            password,
            win32security.LOGON32_LOGON_NETWORK,
            win32security.LOGON32_PROVIDER_DEFAULT,
        )
        token.Close()
        return True
    except Exception:
        pass

    return False


def _resolve_approver_discipline(user_id: int, access_level: AccessLevel) -> ApproverDiscipline:
    """
    Query APPROVERS table for the given user_id and return their discipline.
    Mirrors the VB block that runs when DBAccessLevel == APPROVER.
    Admin users that have no APPROVERS row get ApproverDiscipline.Admin.
    """
    if access_level == AccessLevel.ADMIN:
        return ApproverDiscipline.Admin

    if access_level != AccessLevel.APPROVER:
        return ApproverDiscipline.NONE

    rows = fetch_approvers_by_user_id_all(user_id)
    if not rows:
        return ApproverDiscipline.NONE

    # Pick the first active row; if none active, return NONE
    active = [r for r in rows if str(r.get("ACTIVE", "")).strip().lower() in ("true", "1")]
    target = active[0] if active else rows[0]

    try:
        return ApproverDiscipline(int(target["APPROVER_TYPE_ID"]))
    except (KeyError, ValueError, TypeError):
        return ApproverDiscipline.NONE


def _set_fallback_user(username: str) -> None:
    """
    Grant READ_ONLY access for a Windows-authenticated user whose account
    exists in AD but whose Windows login lacks SELECT on METER_SPECS.dbo.USERS.
    Used as a temporary fallback until the DBA grants table permissions.
    """
    user = User(
        username=username,
        first_name=username,
        access_level=AccessLevel.READ_ONLY,
        approver_discipline=ApproverDiscipline.NONE,
    )
    set_current_user(user)


def authenticate(username: str, password: str) -> tuple[bool, str]:
    """
    Full authentication sequence matching frmLogin.vb > LogOnToFR_Database().

    Returns (success: bool, message: str).
    On success the module-level current_user is populated.
    """
    domain_validated = _try_ad_validate(username, password)

    try:
        user_row = fetch_user_by_username(username)
    except PermissionError:
        # SQL Server permission denied on METER_SPECS.dbo.USERS.
        # If Windows AD validated the user, let them in as READ_ONLY so they
        # can still use the app while the DBA grants table-level SELECT rights.
        if domain_validated:
            _set_fallback_user(username)
            return True, "__AD_ONLY__"
        # No AD validation and no DB access — nothing we can do.
        return False, (
            "Cannot read user records from the database and Windows AD "
            "authentication also failed.\n\n"
            "Ask your DBA to run:\n"
            "  USE METER_SPECS;\n"
            "  GRANT SELECT ON [dbo].[USERS]    TO [DOMAIN\\your_username];\n"
            "  GRANT SELECT ON [dbo].[APPROVERS] TO [DOMAIN\\your_username];"
        )

    if user_row is None:
        return False, "Username not found. Check your username and password and try again."

    # Normalize the row keys to lowercase for reliable access
    user_row = {k.lower(): v for k, v in user_row.items()}

    db_password = str(user_row.get("password",        "") or "").strip()
    db_first     = str(user_row.get("firstname",       "") or "").strip()
    db_last      = str(user_row.get("lastname",        "") or "").strip()
    db_email     = str(user_row.get("email",           "") or "").strip()
    db_active    = user_row.get("active",       False)
    db_pw_reset  = user_row.get("passwordisreset", False)
    db_user_id   = int(user_row.get("id", 0) or 0)
    db_access    = user_row.get("accesslevel", 0)

    try:
        db_access = AccessLevel(int(user_row.get("accesslevel", 0) or 0))
    except (ValueError, TypeError):
        db_access = AccessLevel.READ_ONLY

    # Password check
    if not domain_validated and password.strip() != db_password:
        return False, "Incorrect password. Check your username and password and try again."

    # Active check
    if not db_active and str(db_active).strip().lower() not in ("true", "1"):
        return False, "User account is not active. Please contact your administrator."

    # Password reset flag
    if db_pw_reset and str(db_pw_reset).strip().lower() in ("true", "1"):
        return False, "__PASSWORD_RESET__"   # caller opens change-password dialog

    # Resolve approver discipline
    discipline = _resolve_approver_discipline(db_user_id, db_access)

    user = User(
        user_id=db_user_id,
        username=username,
        first_name=db_first,
        last_name=db_last,
        email=db_email,
        access_level=db_access,
        approver_discipline=discipline,
        password=db_password,
    )
    set_current_user(user)
    return True, "OK"


# ---------------------------------------------------------------------------
# Login dialog
# ---------------------------------------------------------------------------

class LoginDialog(QDialog):
    """
    Login window.  Exec this before showing the DashboardWindow.
    Accepted = user authenticated (or chose Browse mode).
    Rejected = user cancelled / closed the window.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Failure Report Database — Login")
        self.setFixedWidth(380)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        self._build_ui()
        self._restore_username()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(20, 20, 20, 20)

        # Title
        title = QLabel("Failure Report Database")
        font = QFont()
        font.setPointSize(13)
        font.setBold(True)
        title.setFont(font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(title)

        sub = QLabel("Please log in to continue")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet("color: #666;")
        root.addWidget(sub)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(sep)

        # Form
        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)

        self._username = QLineEdit()
        self._username.setPlaceholderText("Domain username")
        form.addRow("Username:", self._username)

        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        self._password.setPlaceholderText("Password")
        self._password.returnPressed.connect(self._on_login)
        form.addRow("Password:", self._password)

        root.addLayout(form)

        # Error label
        self._error_label = QLabel("")
        self._error_label.setWordWrap(True)
        self._error_label.setStyleSheet("color: #c0392b; font-size: 9pt;")
        self._error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._error_label)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._login_btn = QPushButton("Log In")
        self._login_btn.setDefault(True)
        self._login_btn.setShortcut(QKeySequence("Return"))
        self._login_btn.clicked.connect(self._on_login)
        btn_row.addWidget(self._login_btn)

        browse_btn = QPushButton("Browse (Read Only)")
        browse_btn.setToolTip("Open in read-only mode without logging in")
        browse_btn.clicked.connect(self._on_browse)
        btn_row.addWidget(browse_btn)

        root.addLayout(btn_row)

        cancel_btn = QPushButton("Exit")
        cancel_btn.clicked.connect(self.reject)
        root.addWidget(cancel_btn)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _restore_username(self):
        settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        saved = settings.value(SETTINGS_USERNAME, "")
        # Fall back to the current Windows login name if nothing was saved
        if not saved:
            try:
                saved = getpass.getuser()
            except Exception:
                saved = ""
        if saved:
            self._username.setText(saved)
            self._password.setFocus()

    def _save_username(self, username: str):
        settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        settings.setValue(SETTINGS_USERNAME, username)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_login(self):
        username = self._username.text().strip()
        password = self._password.text()

        if not username:
            self._error_label.setText("Please enter your username.")
            return

        self._login_btn.setEnabled(False)
        self._error_label.setText("Authenticating…")

        success, message = authenticate(username, password)

        self._login_btn.setEnabled(True)

        if success and message == "__AD_ONLY__":
            self._save_username(username)
            self._password.clear()
            QMessageBox.warning(
                self,
                "Limited Access — Read Only",
                "Windows AD authentication succeeded, but your account does not have "
                "permission to read user records from the database.\n\n"
                "You have been granted Read-Only access.\n\n"
                "To get your full access level, ask your DBA to run:\n"
                "  USE METER_SPECS;\n"
                f"  GRANT SELECT ON [dbo].[USERS]     TO [DOMAIN\\{username}];\n"
                f"  GRANT SELECT ON [dbo].[APPROVERS]  TO [DOMAIN\\{username}];",
            )
            self.accept()
        elif success:
            self._save_username(username)
            self._password.clear()
            self.accept()
        elif message == "__PASSWORD_RESET__":
            self._error_label.setText("")
            self._password.clear()
            self._open_change_password(username)
        else:
            self._error_label.setText(message)

    def _on_browse(self):
        """Read-only access — mirrors frmLogin btnBrowseFailureReports_Click."""
        user = User(
            username="Default",
            first_name="Browser",
            access_level=AccessLevel.READ_ONLY,
            approver_discipline=ApproverDiscipline.NONE,
        )
        set_current_user(user)
        self.accept()

    def _open_change_password(self, username: str):
        """Open the change-password dialog when PASSWORDISRESET flag is set."""
        from ui.change_password import ChangePasswordDialog
        dlg = ChangePasswordDialog(username=username, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            QMessageBox.information(
                self,
                "Password Changed",
                "Password changed successfully. Please log in with your new password.",
            )
        else:
            self._error_label.setText(
                "Password change required. Please log in again and change your password."
            )


# ---------------------------------------------------------------------------
# Convenience helper
# ---------------------------------------------------------------------------

def run_login(parent=None) -> bool:
    """
    Show the login dialog and return True if the user successfully authenticated.
    Populates auth.session.current_user on success.
    """
    dlg = LoginDialog(parent=parent)
    return dlg.exec() == QDialog.DialogCode.Accepted
