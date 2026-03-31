"""
User session management.

Mirrors the VB enums and User class in frmFailureBrowser.vb:
  eAccessState       — NO_ACCESS, READ_ONLY, CREATE_NEW, CR_EDIT, POWER, APPROVER, ADMIN
  eApproverDiscipline — NONE, Compliance, Engineering, Manufacturing,
                        Product_Managment, Quality_Product_Delivery, Admin, SYSTEMS

The module exposes a single module-level `current_user` instance that is
populated by the login dialog and read everywhere else in the app.
"""

from enum import IntEnum


class AccessLevel(IntEnum):
    """
    Maps to VB's eAccessState (integer values from the USERS.ACCESSLEVEL column).

    NO_ACCESS   = 0  — no rights at all
    READ_ONLY   = 1  — view reports only
    CREATE_NEW  = 2  — create new reports and edit their failure details
    CR_EDIT     = 3  — edit corrective actions and engineering data
    POWER       = 4  — edit corrective action and failure description
    APPROVER    = 5  — review / approve + edit TCC comments
    ADMIN       = 6  — full access (create, edit, delete, approve)
    """
    NO_ACCESS  = 0
    READ_ONLY  = 1
    CREATE_NEW = 2
    CR_EDIT    = 3
    POWER      = 4
    APPROVER   = 5
    ADMIN      = 6


class ApproverDiscipline(IntEnum):
    """
    Maps to VB's eApproverDiscipline (stored as APPROVERS.APPROVER_TYPE_ID).

    NONE                    = 0
    Compliance              = 1
    Engineering             = 2
    Manufacturing           = 3
    Product_Managment       = 4  (VB spelling retained)
    Quality_Product_Delivery = 5
    Admin                   = 6
    SYSTEMS                 = 7
    """
    NONE                     = 0
    Compliance               = 1
    Engineering              = 2
    Manufacturing            = 3
    Product_Managment        = 4
    Quality_Product_Delivery = 5
    Admin                    = 6
    SYSTEMS                  = 7


class User:
    """
    Mirrors the VB User class on frmFailureBrowser.

    Populated by the login dialog after a successful authentication.
    """

    def __init__(
        self,
        user_id: int = 0,
        username: str = "",
        first_name: str = "",
        last_name: str = "",
        email: str = "",
        access_level: AccessLevel = AccessLevel.NO_ACCESS,
        approver_discipline: ApproverDiscipline = ApproverDiscipline.NONE,
        password: str = "",
    ):
        self.user_id            = user_id
        self.username           = username
        self.first_name         = first_name
        self.last_name          = last_name
        self.email              = email
        self.access_level       = access_level
        self.approver_discipline = approver_discipline
        self._password          = password  # internal / fallback password

    @property
    def full_name(self) -> str:
        name = f"{self.first_name} {self.last_name}".strip()
        return name or self.username

    @property
    def is_logged_in(self) -> bool:
        return self.access_level != AccessLevel.NO_ACCESS

    @property
    def can_create(self) -> bool:
        return self.access_level in (
            AccessLevel.CREATE_NEW,
            AccessLevel.POWER,
            AccessLevel.APPROVER,
            AccessLevel.ADMIN,
        )

    @property
    def can_edit(self) -> bool:
        return self.access_level in (
            AccessLevel.CREATE_NEW,
            AccessLevel.CR_EDIT,
            AccessLevel.POWER,
            AccessLevel.APPROVER,
            AccessLevel.ADMIN,
        )

    @property
    def can_approve(self) -> bool:
        return self.access_level in (AccessLevel.APPROVER, AccessLevel.ADMIN)

    @property
    def can_delete(self) -> bool:
        return self.access_level == AccessLevel.ADMIN

    @property
    def can_edit_tcc(self) -> bool:
        """Can edit TCC approval fields for their assigned discipline."""
        return self.can_approve

    def can_approve_discipline(self, discipline: ApproverDiscipline) -> bool:
        """
        True if this user can sign off on the given TCC discipline.
        Admin approvers can approve any discipline.
        """
        if self.approver_discipline == ApproverDiscipline.Admin:
            return True
        return self.approver_discipline == discipline

    def __repr__(self) -> str:
        return (
            f"User(username={self.username!r}, "
            f"access={self.access_level.name}, "
            f"discipline={self.approver_discipline.name})"
        )


# ---------------------------------------------------------------------------
# Module-level singleton — set by the login dialog, read everywhere else
# ---------------------------------------------------------------------------

current_user: User = User()  # starts as NO_ACCESS / not logged in


def set_current_user(user: User) -> None:
    global current_user
    current_user = user


def clear_session() -> None:
    global current_user
    current_user = User()
