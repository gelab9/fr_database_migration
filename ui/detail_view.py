"""
Detail view dialog — displays all 70 columns for a single failure report
in a 5-tab read-only layout.

Opens from the dashboard on row double-click. Receives the [Index] PK,
fetches via fetch_report_by_id(), and populates each tab. The Edit button
toggles all fields to editable; save logic is connected externally via the
save_requested signal.

Day 3 changes
-------------
* Delete button added — fires delete_report() after two-step confirmation,
  then emits report_deleted(index) so the dashboard can refresh.
* Print / Export to PDF button added — renders all fields to a formatted
  HTML string and passes it to QPrinter via QTextDocument, producing a
  clean single-page (or multi-page) PDF the user can save or print.
* Keyboard shortcut: Ctrl+W / Escape closes the dialog when not in edit mode.
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QKeySequence
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from auth.session import AccessLevel, ApproverDiscipline, current_user
from db.lookup_queries import (
    fetch_amr_manufacturers,
    fetch_amr_models,
    fetch_amr_subtypes,
    fetch_amr_types,
    fetch_approvers_by_discipline,
    fetch_meter_bases,
    fetch_meter_forms,
    fetch_meter_manufacturers,
    fetch_meter_models,
    fetch_meter_subtypes,
    fetch_meter_types,
    fetch_test_levels,
    fetch_test_names,
    fetch_test_types,
    fetch_testers,
)
import os
import tempfile

from db.queries import (
    delete_attachment_by_id,
    delete_report,
    fetch_attachment_blob,
    fetch_attachments_by_new_id,
    fetch_report_by_id,
    insert_attachment,
    update_report,
)

# DB keys whose edit-mode widget is an editable QComboBox populated from METER_SPECS.
# Mirrors VB: combos allow free-text entry AND pre-defined lookup values.
_COMBO_LOADERS: dict[str, callable] = {
    "Test_Type":          lambda: [""] + (fetch_test_types() or []),
    "Level":              lambda: [""] + fetch_test_levels(),
    "Test":               lambda: [""] + fetch_test_names(),
    "Tested By":          lambda: [""] + fetch_testers(),
    "Meter":              lambda: [""] + fetch_meter_models(),
    "Meter_Manufacturer": lambda: [""] + fetch_meter_manufacturers(),
    "Meter_Type":         lambda: [""] + fetch_meter_types(),
    "Meter_SubType":      lambda: [""] + fetch_meter_subtypes(),
    "Form":               lambda: [""] + fetch_meter_forms(),
    "Meter_Base":         lambda: [""] + fetch_meter_bases(),
    "AMR":                lambda: [""] + fetch_amr_models(),
    "AMR_Manufacturer":   lambda: [""] + fetch_amr_manufacturers(),
    "AMR_Type":           lambda: [""] + fetch_amr_types(),
    "AMR_SUBType":        lambda: [""] + fetch_amr_subtypes(),
    "EUT_TYPE":           lambda: ["", "AMI", "Meter Only", "AMR Only", "OTHER EUT"],
    # TCC approval combos — populated from APPROVERS table per discipline
    "TCC 1": lambda: [""] + fetch_approvers_by_discipline("Compliance"),
    "TCC 2": lambda: [""] + fetch_approvers_by_discipline("Development Engineering"),
    "TCC 3": lambda: [""] + fetch_approvers_by_discipline("Manufacturing"),
    "TCC 4": lambda: [""] + fetch_approvers_by_discipline("Product Management"),
    "TCC 5": lambda: [""] + fetch_approvers_by_discipline("Supplier Quality"),
    "TCC 6": lambda: [""] + fetch_approvers_by_discipline("Systems"),
}

# DB keys stored as nvarchar "Checked"/"Unchecked" — rendered as QCheckBox.
# Mirrors VB CheckBox controls bound to these columns.
_BOOL_KEYS: set[str] = {
    "TCC_Review_Required",
    "FR_Ready_For_Review",
    "FR_Approved",
    "Pass",
    "Anomaly",
    "Failed_Sample_Ready",
}

# TCC column → (ApproverDiscipline enum member, APPROVERS.DISCIPLINE string)
# Used to gate per-discipline editability (matches VB lines 1059-1134).
_TCC_DISCIPLINE_MAP: dict[str, tuple] = {
    "TCC 1": (ApproverDiscipline.Compliance,               "Compliance"),
    "TCC 2": (ApproverDiscipline.Engineering,               "Development Engineering"),
    "TCC 3": (ApproverDiscipline.Manufacturing,             "Manufacturing"),
    "TCC 4": (ApproverDiscipline.Product_Managment,         "Product Management"),
    "TCC 5": (ApproverDiscipline.Quality_Product_Delivery,  "Supplier Quality"),
    "TCC 6": (ApproverDiscipline.SYSTEMS,                   "Systems"),
}

_TCC_KEYS: set[str] = set(_TCC_DISCIPLINE_MAP.keys())


def _can_edit_tcc(tcc_key: str) -> bool:
    """
    Return True if the current user may edit the given TCC slot.
    Mirrors VB: only the matching discipline approver (or Admin) can write their TCC field.
    """
    if current_user.access_level.value < AccessLevel.APPROVER.value:
        return False
    if current_user.approver_discipline == ApproverDiscipline.Admin:
        return True
    disc_enum = _TCC_DISCIPLINE_MAP.get(tcc_key, (None,))[0]
    return disc_enum is not None and disc_enum == current_user.approver_discipline


# ---------------------------------------------------------------------------
# Field definitions per tab
# Each entry: (display label, db dict key)
# Keys match column names exactly as returned by pyodbc cursor.description.
# ---------------------------------------------------------------------------

METER_FIELDS = [
    ("EUT Type",        "EUT_TYPE"),
    ("Manufacturer",    "Meter_Manufacturer"),
    ("Meter",           "Meter"),
    ("Meter Type",      "Meter_Type"),
    ("Sub Type",        "Meter_SubType"),
    ("Sub Type II",     "Meter_SubTypeII"),
    ("DSP Rev",         "Meter_DSP_Rev"),
    ("PCBA",            "Meter_PCBA"),
    ("PCBA Rev",        "Meter_PCBA_Rev"),
    ("Software",        "Meter_Software"),
    ("Software Rev",    "Meter_Software_Rev"),
    ("Voltage",         "Meter_Voltage"),
    ("Form",            "Form"),
    ("Base",            "Meter_Base"),
    ("Serial Number",   "Meter_Serial_Number"),
    ("Notes",           "Meter_Notes"),
]

AMR_FIELDS = [
    ("AMR",             "AMR"),
    ("AMR Rev",         "AMR Rev"),
    ("Manufacturer",    "AMR_Manufacturer"),
    ("Serial Number",   "AMR_SN"),
    ("Type",            "AMR_Type"),
    ("Sub Type",        "AMR_SUBType"),
    ("Sub Type II",     "AMR_SUBTypeII"),
    ("Sub Type III",    "AMR_SUBTypeIII"),
    ("Notes",           "AMR_Notes"),
    ("PCBA",            "AMR_PCBA"),
    ("PCBA Rev",        "AMR_PCBA_Rev"),
    ("Software",        "AMR_Software"),
    ("Software Rev",    "AMR_Software_Rev"),
    ("IP / LAN ID",     "AMR_IP_LAN_ID"),
    ("Voltage",         "AMR_Voltage"),
]

TEST_INFO_FIELDS = [
    ("Project",             "Project"),
    ("Project Number",      "Project_Number"),
    ("FW Ver",              "FW Ver"),
    ("Test Matrix ID",      "Test_Matrix_ID"),
    ("Test",                "Test"),
    ("Test Type",           "Test_Type"),
    ("Level",               "Level"),
    ("Date Failed",         "Date Failed"),
    ("Tested By",           "Tested By"),
    ("Assigned To",         "Assigned To"),
    ("Test Equipment ID",   "Test_Equipment_ID"),
]

FAILURE_FIELDS = [
    ("Failure Description", "Failure Description"),
    ("Corrective Action",   "Corrective Action"),
]

ENGINEERING_FIELDS = [
    ("Engineering Notes",   "Engineering Notes"),
]

REVIEW_FIELDS = [
    ("TCC 1",                    "TCC 1"),
    ("TCC 2",                    "TCC 2"),
    ("TCC 3",                    "TCC 3"),
    ("TCC 4",                    "TCC 4"),
    ("TCC 5",                    "TCC 5"),
    ("TCC 6",                    "TCC 6"),
    ("TCC Comments",             "TCC Comments"),
    ("TCC Review Required",      "TCC_Review_Required"),
    ("FR Ready For Review",      "FR_Ready_For_Review"),
    ("FR Approved",              "FR_Approved"),
    ("Approved By",              "Approved By"),
    ("Date Approved",            "Date Approved"),
    ("Date Closed",              "Date Closed"),
    ("Corrected By",             "Corrected By"),
    ("Date Corrected",           "Date Corrected"),
    ("Pass",                     "Pass"),
    ("Anomaly",                  "Anomaly"),
    ("Failed Sample Ready",      "Failed_Sample_Ready"),
    ("Failed Sample Ready Date", "Failed_Sample_Ready_Date"),
]

# Fields that get a QTextEdit instead of a QLineEdit
MULTILINE_KEYS = {
    "Meter_Notes",
    "AMR_Notes",
    "Failure Description",
    "Corrective Action",
    "Engineering Notes",
    "TCC Comments",
}

# These are the only field on their tab so they get extra vertical space
LARGE_MULTILINE_KEYS = {"Failure Description", "Corrective Action", "Engineering Notes"}

# Stylesheet applied to widgets in read-only mode to look like display labels
_READONLY_STYLE = (
    "QLineEdit[readOnly='true'] {"
    "  background: transparent;"
    "  border: none;"
    "  border-bottom: 1px solid #ccc;"
    "  border-radius: 0;"
    "  padding: 1px 2px;"
    "}"
    "QTextEdit[readOnly='true'] {"
    "  background: transparent;"
    "  border: 1px solid #ccc;"
    "}"
)

_EDITABLE_STYLE = ""   # revert to Qt default


# ---------------------------------------------------------------------------
# Detail dialog
# ---------------------------------------------------------------------------

class DetailDialog(QDialog):
    """
    Read-only / editable detail view for a single failure report.

    Signals
    -------
    save_requested : int, dict
        Emitted when the user clicks Save in edit mode.
        Carries (index, fields) where fields maps every editable column
        name to its current widget value.
    report_deleted : int
        Emitted (with [Index]) when the report has been successfully deleted,
        so the dashboard can refresh.
    """

    save_requested = pyqtSignal(int, dict)
    report_deleted = pyqtSignal(int)

    def __init__(self, index: int, parent=None, prompt_before_saving: bool = True):
        super().__init__(parent)
        self._index = index
        self._editing = False
        self._prompt_before_saving = prompt_before_saving
        # Maps db key → QWidget (QLineEdit or QTextEdit)
        self._field_widgets: dict[str, QWidget] = {}

        self.setWindowTitle("Failure Report Detail")
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )

        self._report = fetch_report_by_id(index)
        if self._report is None:
            QMessageBox.critical(self, "Error", f"Report with Index {index} not found.")
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, self.reject)
            return

        self._build_ui()
        self._populate()
        self.showMaximized()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(12, 12, 12, 12)

        # ── Header ─────────────────────────────────────────────────────
        header_row = QHBoxLayout()

        self._title_label = QLabel()
        title_font = QFont()
        title_font.setPointSize(13)
        title_font.setBold(True)
        self._title_label.setFont(title_font)
        self._title_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        header_row.addWidget(self._title_label)

        # Submit for Review — POWER+ users (sets FR_READY_FOR_REVIEW=Checked and saves)
        self._submit_review_btn = QPushButton("Submit for Review")
        self._submit_review_btn.setObjectName("submit_review_btn")
        self._submit_review_btn.setToolTip("Mark this report as Ready for TCC Review")
        self._submit_review_btn.setVisible(current_user.can_create)
        self._submit_review_btn.clicked.connect(self._on_submit_review_clicked)
        header_row.addWidget(self._submit_review_btn)

        # Edit button — hidden for READ_ONLY / NO_ACCESS (matches VB access gating)
        self._edit_btn = QPushButton("Edit")
        self._edit_btn.setFixedWidth(70)
        self._edit_btn.setVisible(current_user.can_edit)
        self._edit_btn.clicked.connect(self._on_edit_clicked)
        header_row.addWidget(self._edit_btn)

        self._save_btn = QPushButton("Save")
        self._save_btn.setObjectName("save_btn")
        self._save_btn.setFixedWidth(70)
        self._save_btn.setVisible(False)
        self._save_btn.clicked.connect(self._on_save_clicked)
        header_row.addWidget(self._save_btn)

        self._pdf_btn = QPushButton("Export PDF")
        self._pdf_btn.setObjectName("pdf_btn")
        self._pdf_btn.setFixedWidth(90)
        self._pdf_btn.setToolTip("Export this report as a PDF file")
        self._pdf_btn.clicked.connect(self._on_export_pdf)
        header_row.addWidget(self._pdf_btn)

        # Delete button — ADMIN only (matches VB eAccessState.ADMIN gate)
        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setObjectName("delete_btn")
        self._delete_btn.setFixedWidth(70)
        self._delete_btn.setToolTip("Permanently delete this report")
        self._delete_btn.setVisible(current_user.can_delete)
        self._delete_btn.clicked.connect(self._on_delete_clicked)
        header_row.addWidget(self._delete_btn)

        self._close_btn = QPushButton("Close")
        self._close_btn.setFixedWidth(70)
        self._close_btn.setShortcut(QKeySequence("Ctrl+W"))
        self._close_btn.clicked.connect(self.reject)
        header_row.addWidget(self._close_btn)

        root.addLayout(header_row)

        # ── Separator ──────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(sep)

        # ── Tabs ───────────────────────────────────────────────────────
        self._tabs = QTabWidget()
        root.addWidget(self._tabs)

        self._tabs.addTab(self._build_form_tab(METER_FIELDS),        "Meter Info")
        self._tabs.addTab(self._build_form_tab(AMR_FIELDS),          "AMR Info")
        self._tabs.addTab(self._build_form_tab(TEST_INFO_FIELDS),    "Test Info")
        self._tabs.addTab(self._build_form_tab(FAILURE_FIELDS),      "Failure")
        self._tabs.addTab(self._build_form_tab(ENGINEERING_FIELDS),  "Engineering")
        self._tabs.addTab(self._build_form_tab(REVIEW_FIELDS),       "Review && Approval")
        self._tabs.addTab(self._build_attachments_tab(),             "Attachments")

        # Wire TCC combos + TCC_Review_Required checkbox to auto-approve logic.
        # Matches VB's CheckedChanged / TextChanged handlers (lines 5442-5466).
        for tcc_key in _TCC_KEYS:
            w = self._field_widgets.get(tcc_key)
            if isinstance(w, QComboBox):
                w.currentTextChanged.connect(self._check_auto_approve)
        rfr_w = self._field_widgets.get("TCC_Review_Required")
        if isinstance(rfr_w, QCheckBox):
            rfr_w.stateChanged.connect(self._check_auto_approve)
        dc_w = self._field_widgets.get("Date Corrected")
        if isinstance(dc_w, QLineEdit):
            dc_w.textChanged.connect(self._check_auto_approve)

        self.setStyleSheet(_READONLY_STYLE)

    def _build_form_tab(self, field_defs: list[tuple[str, str]]) -> QScrollArea:
        """Build a scrollable QFormLayout tab for the given field definitions."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        form = QFormLayout(container)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(6)
        form.setContentsMargins(12, 12, 12, 12)

        for label_text, db_key in field_defs:
            widget = self._make_field_widget(db_key)
            self._field_widgets[db_key] = widget

            label = QLabel(label_text + ":")
            label.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            if db_key in MULTILINE_KEYS:
                label.setAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop
                )
                label.setContentsMargins(0, 4, 0, 0)

            form.addRow(label, widget)

        scroll.setWidget(container)
        return scroll

    def _make_field_widget(self, db_key: str) -> QWidget:
        if db_key in MULTILINE_KEYS:
            w = QTextEdit()
            w.setReadOnly(True)
            w.setMinimumHeight(160 if db_key in LARGE_MULTILINE_KEYS else 80)
            w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            w.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            return w
        if db_key in _BOOL_KEYS:
            w = QCheckBox()
            w.setEnabled(False)   # read-only until Edit is clicked
            return w
        if db_key in _COMBO_LOADERS:
            w = QComboBox()
            w.setEditable(True)   # mirrors VB: user may type a custom value
            w.addItems(_COMBO_LOADERS[db_key]())
            w.setEnabled(False)   # read-only until Edit is clicked
            return w
        w = QLineEdit()
        w.setReadOnly(True)
        return w

    def _build_attachments_tab(self) -> QWidget:
        """
        Tab 5 — Attachment management.

        Section 1: Legacy UNC path (ATTACHMENTS column on the main report row).
                   Read-only display + "Open Folder" button for VB-era ZIP archives.

        Section 2: Binary attachments stored in the ATTACHMENT table (varbinary MAX).
                   Upload, Download/Open, and Delete (POWER+) actions.
        """
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # ── Section 1: Legacy UNC path ────────────────────────────────────
        unc_lbl = QLabel("Legacy attachment path (VB/ZIP archive):")
        unc_lbl.setFont(QFont("", -1, QFont.Weight.Bold))
        layout.addWidget(unc_lbl)

        unc_row = QHBoxLayout()
        self._attachments_field = QLineEdit()
        self._attachments_field.setReadOnly(True)
        self._attachments_field.setPlaceholderText("No legacy UNC path stored")
        unc_row.addWidget(self._attachments_field, stretch=1)

        self._open_folder_btn = QPushButton("Open Folder")
        self._open_folder_btn.setFixedWidth(100)
        self._open_folder_btn.setEnabled(False)
        self._open_folder_btn.setToolTip("Open the folder containing the legacy ZIP archive")
        self._open_folder_btn.clicked.connect(self._on_open_unc_folder)
        unc_row.addWidget(self._open_folder_btn)
        layout.addLayout(unc_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep)

        # ── Section 2: Binary attachments ────────────────────────────────
        bin_lbl = QLabel("File attachments:")
        bin_lbl.setFont(QFont("", -1, QFont.Weight.Bold))
        layout.addWidget(bin_lbl)

        self._attachment_list = QListWidget()
        self._attachment_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._attachment_list.setMinimumHeight(140)
        self._attachment_list.itemSelectionChanged.connect(self._on_attachment_selection_changed)
        layout.addWidget(self._attachment_list, stretch=1)

        att_btn_row = QHBoxLayout()
        att_btn_row.setSpacing(8)

        self._upload_btn = QPushButton("Upload File…")
        self._upload_btn.setToolTip("Attach a file to this report (stored in database)")
        self._upload_btn.clicked.connect(self._on_upload_attachment)
        att_btn_row.addWidget(self._upload_btn)

        self._download_btn = QPushButton("Open / Download")
        self._download_btn.setEnabled(False)
        self._download_btn.setToolTip("Save selected attachment to a temp file and open it")
        self._download_btn.clicked.connect(self._on_download_attachment)
        att_btn_row.addWidget(self._download_btn)

        self._delete_att_btn = QPushButton("Delete")
        self._delete_att_btn.setEnabled(False)
        self._delete_att_btn.setToolTip("Permanently delete selected attachment (POWER users only)")
        self._delete_att_btn.clicked.connect(self._on_delete_attachment)
        att_btn_row.addWidget(self._delete_att_btn)

        att_btn_row.addStretch()
        layout.addLayout(att_btn_row)

        # Hide upload/delete for read-only users; will be refreshed in _populate
        self._upload_btn.setVisible(
            current_user.access_level.value >= AccessLevel.CREATE_NEW.value
        )
        self._delete_att_btn.setVisible(
            current_user.access_level.value >= AccessLevel.POWER.value
        )

        return container

    # ------------------------------------------------------------------
    # Populate
    # ------------------------------------------------------------------

    def _populate(self):
        """Fill every widget from self._report."""
        new_id  = self._report.get("New ID",  "")
        project = self._report.get("Project", "")
        self._title_label.setText(
            f"FR #{new_id}" + (f"  —  {project}" if project else "")
        )

        for db_key, widget in self._field_widgets.items():
            raw = self._report.get(db_key)
            text = "" if raw is None else str(raw)
            if "Date" in db_key and " " in text:
                text = text.split(" ")[0]

            if isinstance(widget, QTextEdit):
                widget.setPlainText(text)
            elif isinstance(widget, QCheckBox):
                widget.setChecked(text.strip() == "Checked")
            elif isinstance(widget, QComboBox):
                idx = widget.findText(text)
                if idx >= 0:
                    widget.setCurrentIndex(idx)
                else:
                    widget.setCurrentText(text)  # free-text value not in list
            else:
                widget.setText(text)

        # Attachments tab — legacy UNC path
        inline_val = self._report.get("Attachments")
        unc_path = "" if inline_val is None else str(inline_val).strip()
        self._attachments_field.setText(unc_path)
        self._open_folder_btn.setEnabled(bool(unc_path))

        # Attachments tab — binary attachment list
        self._refresh_attachment_list()

    # ------------------------------------------------------------------
    # Attachment helpers
    # ------------------------------------------------------------------

    def _refresh_attachment_list(self):
        """Reload the ATTACHMENT table list for the current report."""
        self._attachment_list.clear()
        new_id_val = self._report.get("New ID") if self._report else None
        if new_id_val is None:
            return
        try:
            rows = fetch_attachments_by_new_id(int(new_id_val))
            for row in rows:
                att_id = row.get("ID")
                item_text = f"Attachment #{att_id}"
                self._attachment_list.addItem(item_text)
                # Store the DB ID in the item's user data
                item = self._attachment_list.item(self._attachment_list.count() - 1)
                item.setData(Qt.ItemDataRole.UserRole, att_id)
        except Exception as e:
            print(f"_refresh_attachment_list error: {e}")
        self._on_attachment_selection_changed()

    def _on_attachment_selection_changed(self):
        has_sel = self._attachment_list.currentItem() is not None
        self._download_btn.setEnabled(has_sel)
        if current_user.access_level.value >= AccessLevel.POWER.value:
            self._delete_att_btn.setEnabled(has_sel)

    def _selected_attachment_id(self) -> int | None:
        item = self._attachment_list.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _on_open_unc_folder(self):
        """Open Explorer to the folder containing the legacy UNC path."""
        path = self._attachments_field.text().strip()
        if not path:
            return
        folder = os.path.dirname(path) if os.path.splitext(path)[1] else path
        try:
            os.startfile(folder)
        except Exception as e:
            QMessageBox.warning(self, "Cannot Open Folder",
                                f"Could not open folder:\n{folder}\n\n{e}")

    def _on_upload_attachment(self):
        """Choose a file and store it as varbinary in the ATTACHMENT table."""
        new_id_val = self._report.get("New ID") if self._report else None
        if new_id_val is None:
            QMessageBox.warning(self, "Upload", "Report must be saved before uploading attachments.")
            return

        path, _ = QFileDialog.getOpenFileName(self, "Select File to Attach")
        if not path:
            return

        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError as e:
            QMessageBox.critical(self, "Upload Failed", f"Could not read file:\n{e}")
            return

        new_att_id = insert_attachment(int(new_id_val), data)
        if new_att_id is None:
            QMessageBox.critical(self, "Upload Failed",
                                 "Database insert failed — check console for details.")
            return

        self._refresh_attachment_list()
        # Select the newly uploaded item
        for i in range(self._attachment_list.count()):
            item = self._attachment_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == new_att_id:
                self._attachment_list.setCurrentItem(item)
                break

    def _on_download_attachment(self):
        """Fetch binary blob and open it via the OS default application."""
        att_id = self._selected_attachment_id()
        if att_id is None:
            return

        data = fetch_attachment_blob(att_id)
        if data is None:
            QMessageBox.critical(self, "Download Failed",
                                 "Could not retrieve attachment data — check console for details.")
            return

        # Write to a named temp file; keep suffix generic since we have no filename
        suffix = f"_attachment_{att_id}.bin"
        try:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            tmp.write(data)
            tmp.close()
            os.startfile(tmp.name)
        except Exception as e:
            QMessageBox.critical(self, "Open Failed",
                                 f"Could not open attachment:\n{e}")

    def _on_delete_attachment(self):
        """Permanently delete the selected attachment after confirmation."""
        att_id = self._selected_attachment_id()
        if att_id is None:
            return

        reply = QMessageBox.question(
            self,
            "Delete Attachment",
            f"Permanently delete Attachment #{att_id}?\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        ok = delete_attachment_by_id(att_id)
        if ok:
            self._refresh_attachment_list()
        else:
            QMessageBox.critical(self, "Delete Failed",
                                 "Could not delete attachment — check console for details.")

    # ------------------------------------------------------------------
    # Edit / save toggle
    # ------------------------------------------------------------------

    def _set_editable(self, editable: bool):
        """Toggle all field widgets between read-only and editable."""
        self._editing = editable

        for db_key, widget in self._field_widgets.items():
            if isinstance(widget, QTextEdit):
                widget.setReadOnly(not editable)
            elif isinstance(widget, QCheckBox):
                # FR_Approved is auto-managed by _check_auto_approve — never manually toggled
                if db_key == "FR_Approved":
                    widget.setEnabled(False)
                else:
                    widget.setEnabled(editable)
            elif isinstance(widget, QComboBox):
                if db_key in _TCC_KEYS:
                    # Gate per-discipline: only the matching approver (or Admin) can edit
                    widget.setEnabled(editable and _can_edit_tcc(db_key))
                else:
                    widget.setEnabled(editable)
            elif isinstance(widget, QLineEdit):
                widget.setReadOnly(not editable)

        self._edit_btn.setText("Cancel" if editable else "Edit")
        self._save_btn.setVisible(editable)
        # Hide destructive buttons while in edit mode
        self._delete_btn.setVisible(not editable)
        self._pdf_btn.setVisible(not editable)

        self.setStyleSheet(_EDITABLE_STYLE if editable else _READONLY_STYLE)

    def _on_edit_clicked(self):
        if self._editing:
            self._populate()
            self._set_editable(False)
        else:
            self._set_editable(True)

    def _on_save_clicked(self):
        """Collect all field values and emit save_requested."""
        if self._prompt_before_saving:
            reply = QMessageBox.question(
                self,
                "Confirm Save",
                "Save changes to this report?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        fields = {}
        for db_key, widget in self._field_widgets.items():
            if isinstance(widget, QTextEdit):
                fields[db_key] = widget.toPlainText() or None
            elif isinstance(widget, QCheckBox):
                fields[db_key] = "Checked" if widget.isChecked() else "Unchecked"
            elif isinstance(widget, QComboBox):
                text = widget.currentText().strip()
                fields[db_key] = text or None
            elif isinstance(widget, QLineEdit):
                text = widget.text().strip()
                fields[db_key] = text or None

        self.save_requested.emit(self._index, fields)

    def _check_auto_approve(self, *_):
        """
        Auto-approval state machine — mirrors VB frmFailureBrowser lines 5442-5466.

        Conditions to auto-approve (set FR_Approved = Checked):
          • TCC_Review_Required = Checked
          • All of TCC 1-6 have a non-empty approver name
          • Date Corrected is non-empty
        If TCC_Review_Required is Checked but conditions not met → FR_Approved = Unchecked.
        """
        if not self._editing:
            return

        tcc_req_w   = self._field_widgets.get("TCC_Review_Required")
        fr_appr_w   = self._field_widgets.get("FR_Approved")
        date_corr_w = self._field_widgets.get("Date Corrected")
        date_appr_w = self._field_widgets.get("Date Approved")
        date_cls_w  = self._field_widgets.get("Date Closed")

        if not (tcc_req_w and fr_appr_w and date_corr_w):
            return

        tcc_required = (
            tcc_req_w.isChecked()
            if isinstance(tcc_req_w, QCheckBox)
            else tcc_req_w.text().strip() == "Checked"
        )

        # Check all six TCC slots are filled
        tcc_all_filled = True
        for tcc_key in ("TCC 1", "TCC 2", "TCC 3", "TCC 4", "TCC 5", "TCC 6"):
            w = self._field_widgets.get(tcc_key)
            if w is None:
                tcc_all_filled = False
                break
            val = (w.currentText().strip() if isinstance(w, QComboBox)
                   else w.text().strip())
            if not val:
                tcc_all_filled = False
                break

        date_corrected = (
            date_corr_w.text().strip() if isinstance(date_corr_w, QLineEdit) else ""
        )

        if not isinstance(fr_appr_w, QCheckBox):
            return

        if tcc_required and tcc_all_filled and date_corrected:
            fr_appr_w.setChecked(True)
            # Auto-fill Date Approved if empty
            if isinstance(date_appr_w, QLineEdit) and not date_appr_w.text().strip():
                from datetime import date as _date
                date_appr_w.setText(_date.today().strftime("%Y-%m-%d"))
            # Auto-fill Date Closed to Date Corrected if empty
            if isinstance(date_cls_w, QLineEdit) and not date_cls_w.text().strip():
                date_cls_w.setText(date_corrected)
        elif tcc_required:
            fr_appr_w.setChecked(False)

    def _on_submit_review_clicked(self):
        """
        Set FR_READY_FOR_REVIEW = 'Checked' and immediately persist.
        Visible only for POWER+ users (current_user.can_create).
        Mirrors VB's "Submit for Review" flow.
        """
        reply = QMessageBox.question(
            self,
            "Submit for Review",
            "Mark this report as <b>Ready for TCC Review</b>?\n\nThis will save the record immediately.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Build fields dict from current widget state
        fields: dict = {}
        for db_key, widget in self._field_widgets.items():
            if isinstance(widget, QTextEdit):
                fields[db_key] = widget.toPlainText() or None
            elif isinstance(widget, QCheckBox):
                fields[db_key] = "Checked" if widget.isChecked() else "Unchecked"
            elif isinstance(widget, QComboBox):
                text = widget.currentText().strip()
                fields[db_key] = text or None
            else:
                text = widget.text().strip()
                fields[db_key] = text or None

        # Force the review flag regardless of current checkbox state
        fields["FR_Ready_For_Review"] = "Checked"

        success = update_report(self._index, fields)
        if success:
            self._report["FR_Ready_For_Review"] = "Checked"
            rfr_w = self._field_widgets.get("FR_Ready_For_Review")
            if isinstance(rfr_w, QCheckBox):
                rfr_w.setChecked(True)
            QMessageBox.information(self, "Submitted", "Report marked as Ready for Review.")
        else:
            QMessageBox.critical(self, "Save Failed", "Could not save — please try again.")

    def handle_save_result(self, success: bool):
        """Called by the save_requested handler after update_report() returns."""
        if success:
            QMessageBox.information(self, "Saved", "Report saved successfully.")
            self._set_editable(False)
        else:
            QMessageBox.critical(
                self, "Save Failed", "Save failed — please try again."
            )

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def _on_delete_clicked(self):
        new_id  = self._report.get("New ID",  "?")
        project = self._report.get("Project", "")
        label   = f"FR #{new_id}" + (f" — {project}" if project else "")

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

        success = delete_report(self._index)
        if success:
            self.report_deleted.emit(self._index)
            self.accept()
        else:
            QMessageBox.critical(
                self, "Delete Failed",
                f"Could not delete {label}.\n\n"
                "The record may have already been removed, or a database error occurred."
            )

    # ------------------------------------------------------------------
    # Export to PDF
    # ------------------------------------------------------------------

    def _on_export_pdf(self):
        """Render all fields to HTML and export via QPrinter → PDF."""
        try:
            from PyQt6.QtPrintSupport import QPrinter, QPrintDialog
            from PyQt6.QtGui import QTextDocument
            from PyQt6.QtWidgets import QFileDialog
        except ImportError:
            QMessageBox.warning(
                self, "Not Available",
                "PDF export requires PyQt6.QtPrintSupport.\n"
                "Install it with:  pip install PyQt6-Qt6-PdfSupport  or check your Qt6 installation."
            )
            return

        # Build HTML content
        html = self._build_pdf_html()

        # Ask where to save
        new_id = self._report.get("New ID", "unknown")
        default_name = f"FR_{new_id}.pdf"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Report as PDF",
            default_name,
            "PDF Files (*.pdf)",
        )
        if not path:
            return

        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(path)
        printer.setPageMargins(
            # left, top, right, bottom in mm
            __import__("PyQt6.QtCore", fromlist=["QMarginsF"]).QMarginsF(15, 15, 15, 15)
        )

        doc = QTextDocument()
        doc.setHtml(html)
        doc.print(printer)

        QMessageBox.information(
            self, "Exported",
            f"Report exported to:\n{path}"
        )

    def _build_pdf_html(self) -> str:
        """Return a complete HTML document representing the full report."""
        new_id  = self._report.get("New ID",  "")
        project = self._report.get("Project", "")
        title   = f"Failure Report #{new_id}" + (f" — {project}" if project else "")

        all_tabs = [
            ("Meter Info",        METER_FIELDS),
            ("AMR Info",          AMR_FIELDS),
            ("Test Info",         TEST_INFO_FIELDS),
            ("Failure",           FAILURE_FIELDS),
            ("Engineering",       ENGINEERING_FIELDS),
            ("Review & Approval", REVIEW_FIELDS),
        ]

        def esc(v):
            if v is None:
                return ""
            s = str(v)
            if " " in s and any(c.isdigit() for c in s[:4]):
                s = s.split(" ")[0]
            return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        rows_html = ""
        for tab_name, fields in all_tabs:
            rows_html += (
                f'<tr><td colspan="2" style="background:#f0f0f0;padding:6px 8px;'
                f'font-weight:bold;font-size:11pt;border-top:2px solid #999;">'
                f'{tab_name}</td></tr>\n'
            )
            for label, db_key in fields:
                val = esc(self._report.get(db_key))
                rows_html += (
                    f'<tr>'
                    f'<td style="width:200px;padding:3px 8px;color:#555;'
                    f'white-space:nowrap;vertical-align:top;">{label}:</td>'
                    f'<td style="padding:3px 8px;vertical-align:top;">{val}</td>'
                    f'</tr>\n'
                )

        html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: Arial, sans-serif; font-size: 10pt; color: #222; }}
  h1   {{ font-size: 14pt; margin-bottom: 4px; }}
  p    {{ margin: 2px 0 10px 0; color: #666; font-size: 9pt; }}
  table {{ width: 100%; border-collapse: collapse; }}
  tr:nth-child(even) td {{ background: #fafafa; }}
</style>
</head>
<body>
<h1>{esc(title)}</h1>
<p>Generated by FR Database Management System</p>
<table>
{rows_html}
</table>
</body>
</html>"""
        return html

    # ------------------------------------------------------------------
    # Keyboard: Escape closes when not editing
    # ------------------------------------------------------------------

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and not self._editing:
            self.reject()
        else:
            super().keyPressEvent(event)


# ---------------------------------------------------------------------------
# Wire detail view into the dashboard (helper used by main.py)
# ---------------------------------------------------------------------------

def open_detail(index: int, parent=None, on_deleted=None, prompt_before_saving: bool = True):
    """
    Create a DetailDialog, wire save_requested → update_report, and exec.

    Parameters
    ----------
    on_deleted : callable | None
        Optional zero-argument callback invoked if the report is deleted
        inside the dialog (so the caller can refresh its list).
    prompt_before_saving : bool
        When True, a confirmation dialog is shown before saving.
    """
    dlg = DetailDialog(index, parent=parent, prompt_before_saving=prompt_before_saving)

    def _on_save(idx: int, fields: dict):
        success = update_report(idx, fields)
        dlg.handle_save_result(success)

    dlg.save_requested.connect(_on_save)

    if on_deleted is not None:
        dlg.report_deleted.connect(lambda _idx: on_deleted())

    dlg.exec()
    return dlg