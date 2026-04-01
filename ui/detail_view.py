"""
Detail panel — embedded single-report view inside the main split window.

Layout mirrors frmFailureBrowser:
  ┌──────────────────────────────────────────────────────────────┐
  │  Title (FR # — Project)           [Submit] [Edit] [Save]...  │
  │  ┌─ Report Header ──────────────────────────────────────┐    │
  │  │ Project | Proj# | EUT Type | Matrix ID | FW Ver      │    │
  │  │ Test | Test Type | Level | Tested By | Assigned To   │    │
  │  │ Date Failed | ☑Pass ☑Anomaly ☑Failed ☑TCC ☑Ready    │    │
  │  └──────────────────────────────────────────────────────┘    │
  ├───────────────────┬──────────────────────────────────────────┤
  │  Approval Sidebar │  Description | Corrective Action |       │
  │  TCC 1-6          │  Engineering Notes | Attachments |       │
  │  FR Approved...   │  TCC Comments | Meter/AMR | Log          │
  └───────────────────┴──────────────────────────────────────────┘
"""

import os
import tempfile

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
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
    QSplitter,
    QStackedWidget,
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
from db.queries import (
    delete_attachment_by_id,
    delete_report,
    fetch_attachment_blob,
    fetch_attachments_by_new_id,
    fetch_report_by_id,
    insert_attachment,
    update_report,
)


# ---------------------------------------------------------------------------
# Combo loaders — db_key → callable returning list of choices
# ---------------------------------------------------------------------------

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
    "TCC 1": lambda: [""] + fetch_approvers_by_discipline("Compliance"),
    "TCC 2": lambda: [""] + fetch_approvers_by_discipline("Development Engineering"),
    "TCC 3": lambda: [""] + fetch_approvers_by_discipline("Manufacturing"),
    "TCC 4": lambda: [""] + fetch_approvers_by_discipline("Product Management"),
    "TCC 5": lambda: [""] + fetch_approvers_by_discipline("Supplier Quality"),
    "TCC 6": lambda: [""] + fetch_approvers_by_discipline("Systems"),
}

# Keys stored as "Checked"/"Unchecked" → rendered as QCheckBox
_BOOL_KEYS: set[str] = {
    "TCC_Review_Required",
    "FR_Ready_For_Review",
    "FR_Approved",
    "Pass",
    "Anomaly",
    "Failed_Sample_Ready",
}

# TCC column → (ApproverDiscipline enum, APPROVERS.DISCIPLINE string)
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
    if current_user.access_level.value < AccessLevel.APPROVER.value:
        return False
    if current_user.approver_discipline == ApproverDiscipline.Admin:
        return True
    disc_enum = _TCC_DISCIPLINE_MAP.get(tcc_key, (None,))[0]
    return disc_enum is not None and disc_enum == current_user.approver_discipline


# ---------------------------------------------------------------------------
# Field group definitions — exported for use by new_report.py
# ---------------------------------------------------------------------------

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
    ("Project Lead",         "Assigned To"),
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

# Keys that get a QTextEdit instead of a QLineEdit (used by new_report.py)
MULTILINE_KEYS: set[str] = {
    "Meter_Notes", "AMR_Notes",
    "Failure Description", "Corrective Action",
    "Engineering Notes", "TCC Comments",
}

# Full-height multiline keys (used by new_report.py)
LARGE_MULTILINE_KEYS: set[str] = {
    "Failure Description", "Corrective Action", "Engineering Notes",
}

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

# Header panel field rows
_HDR_ROW1 = [
    ("Project",    "Project"),
    ("Proj #",     "Project_Number"),
    ("EUT Type",   "EUT_TYPE"),
    ("Matrix ID",  "Test_Matrix_ID"),
    ("FW Ver",     "FW Ver"),
]
_HDR_ROW2 = [
    ("Test",        "Test"),
    ("Test Type",   "Test_Type"),
    ("Level",       "Level"),
    ("Tested By",   "Tested By"),
    ("Project Lead", "Assigned To"),
    ("Date Failed", "Date Failed"),
]
_HDR_CHECKS = [
    ("Pass",               "Pass"),
    ("Anomaly",            "Anomaly"),
    ("Failed Sample Ready","Failed_Sample_Ready"),
    ("TCC Required",       "TCC_Review_Required"),
    ("Ready for Review",   "FR_Ready_For_Review"),
]

# Approval sidebar
_SIDEBAR_TCC = [
    ("TCC 1", "TCC 1"), ("TCC 2", "TCC 2"), ("TCC 3", "TCC 3"),
    ("TCC 4", "TCC 4"), ("TCC 5", "TCC 5"), ("TCC 6", "TCC 6"),
]
_SIDEBAR_APPROVAL = [
    ("FR Approved",      "FR_Approved"),
    ("Approved By",      "Approved By"),
    ("Date Approved",    "Date Approved"),
    ("Date Closed",      "Date Closed"),
    ("Corrected By",     "Corrected By"),
    ("Date Corrected",   "Date Corrected"),
    ("Fail Sample Date", "Failed_Sample_Ready_Date"),
    ("Test Equip ID",    "Test_Equipment_ID"),
]

# Read-only stylesheet (fields look like display labels)
_READONLY_STYLE = (
    "QLineEdit[readOnly='true'] {"
    "  background: transparent; border: none;"
    "  border-bottom: 1px solid #ccc; border-radius: 0; padding: 1px 2px;"
    "}"
    "QTextEdit[readOnly='true'] {"
    "  background: transparent; border: 1px solid #ddd;"
    "}"
)
_EDITABLE_STYLE = ""


# ---------------------------------------------------------------------------
# Detail Panel — embeddable widget
# ---------------------------------------------------------------------------

class DetailPanel(QWidget):
    """
    Embedded report viewer/editor. Lives in the top pane of the main split window.

    Signals
    -------
    report_deleted : int   — emitted (with [Index]) after a successful delete
    report_saved   :       — emitted after a successful save
    """

    report_deleted = pyqtSignal(int)
    report_saved   = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._index:   int | None  = None
        self._report:  dict | None = None
        self._editing: bool        = False
        self._field_widgets: dict[str, QWidget] = {}
        self._build_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_report(self, index: int) -> bool:
        """Fetch and display a report by its [Index] PK. Returns True on success."""
        report = fetch_report_by_id(index)
        if report is None:
            return False
        self._index  = index
        self._report = report
        if self._editing:
            self._set_editable(False)
        self._populate()
        self._stacked.setCurrentIndex(1)
        return True

    def clear(self):
        """Return to empty 'no report selected' state."""
        self._index  = None
        self._report = None
        if self._editing:
            self._set_editable(False)
        self._stacked.setCurrentIndex(0)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._stacked = QStackedWidget()
        root.addWidget(self._stacked)

        # Page 0 — empty placeholder
        empty_page = QWidget()
        el = QVBoxLayout(empty_page)
        lbl = QLabel("Select a report from the list below")
        lbl.setObjectName("empty_detail_label")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        el.addWidget(lbl)
        self._stacked.addWidget(empty_page)

        # Page 1 — report content
        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(8, 6, 8, 6)
        cl.setSpacing(4)

        cl.addLayout(self._build_action_row())
        cl.addWidget(self._build_header_panel())

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        cl.addWidget(sep)

        body = QSplitter(Qt.Orientation.Horizontal)
        body.addWidget(self._build_approval_sidebar())
        body.addWidget(self._build_tabs())
        body.setSizes([230, 900])
        body.setHandleWidth(3)
        body.setChildrenCollapsible(False)
        cl.addWidget(body, stretch=1)

        self._stacked.addWidget(content)
        self._stacked.setCurrentIndex(0)

        self._rewire_signals()
        self.setStyleSheet(_READONLY_STYLE)

    # -- Action buttons row ------------------------------------------------

    def _build_action_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)

        self._title_label = QLabel()
        f = QFont()
        f.setPointSize(12)
        f.setBold(True)
        self._title_label.setFont(f)
        self._title_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        row.addWidget(self._title_label)

        self._submit_review_btn = QPushButton("Submit for Review")
        self._submit_review_btn.setObjectName("submit_review_btn")
        self._submit_review_btn.setVisible(current_user.can_create)
        self._submit_review_btn.clicked.connect(self._on_submit_review_clicked)
        row.addWidget(self._submit_review_btn)

        self._edit_btn = QPushButton("Edit")
        self._edit_btn.setObjectName("edit_btn")
        self._edit_btn.setFixedWidth(70)
        self._edit_btn.setVisible(current_user.can_edit)
        self._edit_btn.clicked.connect(self._on_edit_clicked)
        row.addWidget(self._edit_btn)

        self._save_btn = QPushButton("Save")
        self._save_btn.setObjectName("save_btn")
        self._save_btn.setFixedWidth(70)
        self._save_btn.setVisible(False)
        self._save_btn.clicked.connect(self._on_save_clicked)
        row.addWidget(self._save_btn)

        self._pdf_btn = QPushButton("Export PDF")
        self._pdf_btn.setObjectName("pdf_btn")
        self._pdf_btn.setFixedWidth(90)
        self._pdf_btn.clicked.connect(self._on_export_pdf)
        row.addWidget(self._pdf_btn)

        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setObjectName("delete_btn")
        self._delete_btn.setFixedWidth(70)
        self._delete_btn.setVisible(current_user.can_delete)
        self._delete_btn.clicked.connect(self._on_delete_clicked)
        row.addWidget(self._delete_btn)

        return row

    # -- Report header panel -----------------------------------------------

    def _build_header_panel(self) -> QFrame:
        """Always-visible compact fields — mirrors VB pnlTestinfo."""
        panel = QFrame()
        panel.setObjectName("report_header_panel")
        panel.setFrameShape(QFrame.Shape.StyledPanel)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(4)

        def _field_pair(label: str, key: str, max_w: int = 140) -> QHBoxLayout:
            h = QHBoxLayout()
            h.setSpacing(4)
            lbl = QLabel(label + ":")
            lbl.setStyleSheet("font-size: 8pt; color: #555;")
            lbl.setFixedWidth(len(label) * 6 + 10)
            w = self._make_field_widget(key)
            self._field_widgets[key] = w
            w.setMaximumWidth(max_w)
            if isinstance(w, (QLineEdit, QComboBox)):
                w.setFixedHeight(22)
            h.addWidget(lbl)
            h.addWidget(w)
            return h

        # Row 1
        r1 = QHBoxLayout()
        r1.setSpacing(14)
        for lbl, key in _HDR_ROW1:
            r1.addLayout(_field_pair(lbl, key))
        r1.addStretch()
        layout.addLayout(r1)

        # Row 2
        r2 = QHBoxLayout()
        r2.setSpacing(14)
        for lbl, key in _HDR_ROW2:
            r2.addLayout(_field_pair(lbl, key))
        r2.addStretch()
        layout.addLayout(r2)

        # Row 3 — checkboxes
        r3 = QHBoxLayout()
        r3.setSpacing(18)
        for lbl, key in _HDR_CHECKS:
            w = self._make_field_widget(key)
            self._field_widgets[key] = w
            h = QHBoxLayout()
            h.setSpacing(4)
            h.addWidget(w)
            lbl_w = QLabel(lbl)
            lbl_w.setStyleSheet("font-size: 8pt;")
            h.addWidget(lbl_w)
            r3.addLayout(h)
        r3.addStretch()
        layout.addLayout(r3)

        return panel

    # -- Approval sidebar --------------------------------------------------

    def _build_approval_sidebar(self) -> QWidget:
        """Left sidebar — TCC combos + approval status, mirrors VB pnlApprovals."""
        outer = QWidget()
        outer.setObjectName("approval_sidebar")
        outer.setMinimumWidth(200)
        outer.setMaximumWidth(260)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        inner = QWidget()
        form = QFormLayout(inner)
        form.setSpacing(5)
        form.setContentsMargins(10, 10, 10, 10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # TCC section
        tcc_hdr = QLabel("TCC Approvals")
        tcc_hdr.setObjectName("sidebar_section_header")
        tcc_hdr.setFont(QFont("", -1, QFont.Weight.Bold))
        form.addRow(tcc_hdr)

        for label, key in _SIDEBAR_TCC:
            w = self._make_field_widget(key)
            self._field_widgets[key] = w
            form.addRow(label + ":", w)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        form.addRow(sep)

        # Approval status section
        appr_hdr = QLabel("Approval Status")
        appr_hdr.setObjectName("sidebar_section_header")
        appr_hdr.setFont(QFont("", -1, QFont.Weight.Bold))
        form.addRow(appr_hdr)

        for label, key in _SIDEBAR_APPROVAL:
            w = self._make_field_widget(key)
            self._field_widgets[key] = w
            form.addRow(label + ":", w)

        scroll.setWidget(inner)

        vl = QVBoxLayout(outer)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.addWidget(scroll)

        return outer

    # -- Tab widget --------------------------------------------------------

    def _build_tabs(self) -> QTabWidget:
        """Tab widget matching VB tcReportBody."""
        self._tabs = QTabWidget()
        self._tabs.setObjectName("report_tabs")

        self._tabs.addTab(self._build_text_tab("Failure Description"),  "Description")
        self._tabs.addTab(self._build_text_tab("Corrective Action"),    "Corrective Action")
        self._tabs.addTab(self._build_text_tab("Engineering Notes"),    "Engineering Notes")
        self._tabs.addTab(self._build_attachments_tab(),                "Attachments")
        self._tabs.addTab(self._build_text_tab("TCC Comments"),         "TCC Comments")
        self._tabs.addTab(self._build_meter_amr_tab(),                  "Meter / AMR")
        self._tabs.addTab(self._build_log_tab(),                        "Log")

        return self._tabs

    def _build_text_tab(self, db_key: str) -> QWidget:
        """Single full-height QTextEdit for a text field."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(6, 6, 6, 6)
        w = QTextEdit()
        w.setReadOnly(True)
        w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._field_widgets[db_key] = w
        layout.addWidget(w)
        return container

    def _build_meter_amr_tab(self) -> QWidget:
        """Two-column Meter + AMR layout, matches VB SplitContainerMeterInfoHorz."""
        container = QWidget()
        outer = QHBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        def _make_scroll_form(fields: list, header: str) -> QScrollArea:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            inner = QWidget()
            form = QFormLayout(inner)
            form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            form.setContentsMargins(12, 10, 8, 10)
            form.setSpacing(5)
            hdr = QLabel(header)
            hdr.setFont(QFont("", -1, QFont.Weight.Bold))
            form.addRow(hdr)
            for label, key in fields:
                w = self._make_field_widget(key)
                self._field_widgets[key] = w
                form.addRow(label + ":", w)
            scroll.setWidget(inner)
            return scroll

        outer.addWidget(_make_scroll_form(METER_FIELDS, "Meter"))

        vsep = QFrame()
        vsep.setFrameShape(QFrame.Shape.VLine)
        vsep.setFrameShadow(QFrame.Shadow.Sunken)
        outer.addWidget(vsep)

        outer.addWidget(_make_scroll_form(AMR_FIELDS, "AMR / Comm Module"))

        return container

    def _build_log_tab(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 12, 12, 12)
        lbl = QLabel("Change log not available in current database schema.")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("color: #aaa; font-size: 10pt;")
        layout.addWidget(lbl)
        layout.addStretch()
        return container

    def _build_attachments_tab(self) -> QWidget:
        """Attachment management — UNC legacy path + varbinary upload/download."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # Section 1: legacy UNC path
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
        self._open_folder_btn.clicked.connect(self._on_open_unc_folder)
        unc_row.addWidget(self._open_folder_btn)
        layout.addLayout(unc_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep)

        # Section 2: binary attachments
        bin_lbl = QLabel("File attachments:")
        bin_lbl.setFont(QFont("", -1, QFont.Weight.Bold))
        layout.addWidget(bin_lbl)

        self._attachment_list = QListWidget()
        self._attachment_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._attachment_list.setMinimumHeight(120)
        self._attachment_list.itemSelectionChanged.connect(self._on_attachment_selection_changed)
        layout.addWidget(self._attachment_list, stretch=1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._upload_btn = QPushButton("Upload File…")
        self._upload_btn.clicked.connect(self._on_upload_attachment)
        self._upload_btn.setVisible(current_user.access_level.value >= AccessLevel.CREATE_NEW.value)
        btn_row.addWidget(self._upload_btn)

        self._download_btn = QPushButton("Open / Download")
        self._download_btn.setEnabled(False)
        self._download_btn.clicked.connect(self._on_download_attachment)
        btn_row.addWidget(self._download_btn)

        self._delete_att_btn = QPushButton("Delete")
        self._delete_att_btn.setEnabled(False)
        self._delete_att_btn.clicked.connect(self._on_delete_attachment)
        self._delete_att_btn.setVisible(current_user.access_level.value >= AccessLevel.POWER.value)
        btn_row.addWidget(self._delete_att_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        return container

    # ------------------------------------------------------------------
    # Widget factory
    # ------------------------------------------------------------------

    def _make_field_widget(self, db_key: str) -> QWidget:
        if db_key in _BOOL_KEYS:
            w = QCheckBox()
            w.setEnabled(False)
            return w
        if db_key in _COMBO_LOADERS:
            w = QComboBox()
            w.setEditable(True)
            w.addItems(_COMBO_LOADERS[db_key]())
            w.setEnabled(False)
            return w
        w = QLineEdit()
        w.setReadOnly(True)
        return w

    # ------------------------------------------------------------------
    # Signal wiring (called once after all field_widgets are built)
    # ------------------------------------------------------------------

    def _rewire_signals(self):
        for tcc_key in _TCC_KEYS:
            w = self._field_widgets.get(tcc_key)
            if isinstance(w, QComboBox):
                w.currentTextChanged.connect(self._check_auto_approve)
        tcc_req = self._field_widgets.get("TCC_Review_Required")
        if isinstance(tcc_req, QCheckBox):
            tcc_req.stateChanged.connect(self._check_auto_approve)
        dc_w = self._field_widgets.get("Date Corrected")
        if isinstance(dc_w, QLineEdit):
            dc_w.textChanged.connect(self._check_auto_approve)

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
            raw  = self._report.get(db_key)
            text = "" if raw is None else str(raw)
            if "Date" in db_key:
                if " " in text:
                    text = text.split(" ")[0]
                # Reformat YYYY-MM-DD → MM/DD/YYYY for display
                parts = text.split("-")
                if len(parts) == 3 and all(p.isdigit() for p in parts):
                    text = f"{parts[1]}/{parts[2]}/{parts[0]}"

            if isinstance(widget, QTextEdit):
                widget.setPlainText(text)
            elif isinstance(widget, QCheckBox):
                widget.setChecked(text.strip() == "Checked")
            elif isinstance(widget, QComboBox):
                idx = widget.findText(text)
                if idx >= 0:
                    widget.setCurrentIndex(idx)
                else:
                    widget.setCurrentText(text)
            else:
                widget.setText(text)

        # Attachments tab
        unc = self._report.get("Attachments")
        unc_path = "" if unc is None else str(unc).strip()
        self._attachments_field.setText(unc_path)
        self._open_folder_btn.setEnabled(bool(unc_path))
        self._refresh_attachment_list()

    # ------------------------------------------------------------------
    # Attachment helpers
    # ------------------------------------------------------------------

    def _refresh_attachment_list(self):
        self._attachment_list.clear()
        new_id_val = self._report.get("New ID") if self._report else None
        if new_id_val is None:
            return
        try:
            rows = fetch_attachments_by_new_id(int(new_id_val))
            for row in rows:
                att_id = row.get("ID")
                self._attachment_list.addItem(f"Attachment #{att_id}")
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
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _on_open_unc_folder(self):
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
        new_id_val = self._report.get("New ID") if self._report else None
        if new_id_val is None:
            QMessageBox.warning(self, "Upload", "Report must be saved before uploading.")
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
            QMessageBox.critical(self, "Upload Failed", "Database insert failed.")
            return
        self._refresh_attachment_list()
        for i in range(self._attachment_list.count()):
            item = self._attachment_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == new_att_id:
                self._attachment_list.setCurrentItem(item)
                break

    def _on_download_attachment(self):
        att_id = self._selected_attachment_id()
        if att_id is None:
            return
        data = fetch_attachment_blob(att_id)
        if data is None:
            QMessageBox.critical(self, "Download Failed", "Could not retrieve data.")
            return
        try:
            tmp = tempfile.NamedTemporaryFile(delete=False,
                                              suffix=f"_attachment_{att_id}.bin")
            tmp.write(data)
            tmp.close()
            os.startfile(tmp.name)
        except Exception as e:
            QMessageBox.critical(self, "Open Failed", f"Could not open attachment:\n{e}")

    def _on_delete_attachment(self):
        att_id = self._selected_attachment_id()
        if att_id is None:
            return
        if QMessageBox.question(
            self, "Delete Attachment",
            f"Permanently delete Attachment #{att_id}?\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        ) != QMessageBox.StandardButton.Yes:
            return
        if delete_attachment_by_id(att_id):
            self._refresh_attachment_list()
        else:
            QMessageBox.critical(self, "Delete Failed", "Could not delete attachment.")

    # ------------------------------------------------------------------
    # Edit / save toggle
    # ------------------------------------------------------------------

    def _set_editable(self, editable: bool):
        self._editing = editable
        for db_key, widget in self._field_widgets.items():
            if isinstance(widget, QTextEdit):
                widget.setReadOnly(not editable)
            elif isinstance(widget, QCheckBox):
                widget.setEnabled(False if db_key == "FR_Approved" else editable)
            elif isinstance(widget, QComboBox):
                widget.setEnabled(editable and (_can_edit_tcc(db_key)
                                                if db_key in _TCC_KEYS else True))
            elif isinstance(widget, QLineEdit):
                widget.setReadOnly(not editable)

        self._edit_btn.setText("Cancel" if editable else "Edit")
        self._save_btn.setVisible(editable)
        self._delete_btn.setVisible(not editable and current_user.can_delete)
        self._pdf_btn.setVisible(not editable)
        self.setStyleSheet(_EDITABLE_STYLE if editable else _READONLY_STYLE)

    def _on_edit_clicked(self):
        if self._editing:
            self._populate()
            self._set_editable(False)
        else:
            self._set_editable(True)

    def _collect_fields(self) -> dict:
        """Gather every widget value into a DB-ready dict, converting date display format."""
        fields: dict = {}
        for db_key, widget in self._field_widgets.items():
            if isinstance(widget, QTextEdit):
                fields[db_key] = widget.toPlainText() or None
            elif isinstance(widget, QCheckBox):
                fields[db_key] = "Checked" if widget.isChecked() else "Unchecked"
            elif isinstance(widget, QComboBox):
                fields[db_key] = widget.currentText().strip() or None
            else:
                val = widget.text().strip() or None
                # Convert MM/DD/YYYY display format back to YYYY-MM-DD for DB
                if val and "Date" in db_key:
                    parts = val.split("/")
                    if len(parts) == 3 and all(p.isdigit() for p in parts):
                        val = f"{parts[2]}-{parts[0]}-{parts[1]}"
                fields[db_key] = val
        return fields

    def _on_save_clicked(self):
        if QMessageBox.question(
            self, "Confirm Save", "Save changes to this report?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        ) != QMessageBox.StandardButton.Yes:
            return

        fields = self._collect_fields()

        success = update_report(self._index, fields)
        if success:
            # Reload from DB so display reflects server-side values
            refreshed = fetch_report_by_id(self._index)
            if refreshed:
                self._report = refreshed
            self._set_editable(False)
            self._populate()
            self.report_saved.emit()
        else:
            QMessageBox.critical(self, "Save Failed", "Save failed — please try again.")

    # ------------------------------------------------------------------
    # Auto-approval state machine (mirrors VB lines 5442-5466)
    # ------------------------------------------------------------------

    def _check_auto_approve(self, *_):
        if not self._editing:
            return
        tcc_req_w   = self._field_widgets.get("TCC_Review_Required")
        fr_appr_w   = self._field_widgets.get("FR_Approved")
        date_corr_w = self._field_widgets.get("Date Corrected")
        date_appr_w = self._field_widgets.get("Date Approved")
        date_cls_w  = self._field_widgets.get("Date Closed")
        if not (tcc_req_w and fr_appr_w and date_corr_w):
            return

        tcc_required = (tcc_req_w.isChecked() if isinstance(tcc_req_w, QCheckBox)
                        else tcc_req_w.text().strip() == "Checked")

        tcc_all_filled = all(
            (w.currentText().strip() if isinstance(w, QComboBox) else w.text().strip())
            for key in ("TCC 1", "TCC 2", "TCC 3", "TCC 4", "TCC 5", "TCC 6")
            if (w := self._field_widgets.get(key)) is not None
        )

        date_corrected = (date_corr_w.text().strip()
                          if isinstance(date_corr_w, QLineEdit) else "")

        if not isinstance(fr_appr_w, QCheckBox):
            return

        if tcc_required and tcc_all_filled and date_corrected:
            fr_appr_w.setChecked(True)
            if isinstance(date_appr_w, QLineEdit) and not date_appr_w.text().strip():
                from datetime import date as _date
                date_appr_w.setText(_date.today().strftime("%m/%d/%Y"))
            if isinstance(date_cls_w, QLineEdit) and not date_cls_w.text().strip():
                date_cls_w.setText(date_corrected)
        elif tcc_required:
            fr_appr_w.setChecked(False)

    # ------------------------------------------------------------------
    # Submit for Review
    # ------------------------------------------------------------------

    def _on_submit_review_clicked(self):
        if QMessageBox.question(
            self, "Submit for Review",
            "Mark this report as <b>Ready for TCC Review</b>?\n\nThis saves immediately.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        ) != QMessageBox.StandardButton.Yes:
            return

        fields = self._collect_fields()
        fields["FR_Ready_For_Review"] = "Checked"

        if update_report(self._index, fields):
            self._report["FR_Ready_For_Review"] = "Checked"
            rfr_w = self._field_widgets.get("FR_Ready_For_Review")
            if isinstance(rfr_w, QCheckBox):
                rfr_w.setChecked(True)
            QMessageBox.information(self, "Submitted", "Report marked as Ready for Review.")
        else:
            QMessageBox.critical(self, "Save Failed", "Could not save — please try again.")

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def _on_delete_clicked(self):
        new_id  = self._report.get("New ID",  "?")
        project = self._report.get("Project", "")
        label   = f"FR #{new_id}" + (f" — {project}" if project else "")

        if QMessageBox.question(
            self, "Delete Report",
            f"Permanently delete <b>{label}</b>?\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        ) != QMessageBox.StandardButton.Yes:
            return

        if QMessageBox.question(
            self, "Confirm Delete",
            f"Final confirmation — permanently delete <b>{label}</b>?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        ) != QMessageBox.StandardButton.Yes:
            return

        saved_index = self._index
        if delete_report(saved_index):
            self.clear()
            self.report_deleted.emit(saved_index)
        else:
            QMessageBox.critical(self, "Delete Failed",
                                 f"Could not delete {label}.")

    # ------------------------------------------------------------------
    # Export to PDF
    # ------------------------------------------------------------------

    def _on_export_pdf(self):
        try:
            from PyQt6.QtPrintSupport import QPrinter
            from PyQt6.QtGui import QTextDocument
        except ImportError:
            QMessageBox.warning(self, "Not Available",
                                "PDF export requires PyQt6.QtPrintSupport.")
            return

        html = self._build_pdf_html()
        new_id = self._report.get("New ID", "unknown")
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Report as PDF", f"FR_{new_id}.pdf", "PDF Files (*.pdf)"
        )
        if not path:
            return

        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(path)
        from PyQt6.QtCore import QMarginsF
        printer.setPageMargins(QMarginsF(15, 15, 15, 15))

        doc = QTextDocument()
        doc.setHtml(html)
        doc.print(printer)
        QMessageBox.information(self, "Exported", f"Report exported to:\n{path}")

    def _build_pdf_html(self) -> str:
        new_id  = self._report.get("New ID",  "")
        project = self._report.get("Project", "")
        title   = f"Failure Report #{new_id}" + (f" — {project}" if project else "")

        all_sections = [
            ("Test Info", _HDR_ROW1 + _HDR_ROW2),
            ("Status",    _HDR_CHECKS + _SIDEBAR_APPROVAL),
            ("TCC",       _SIDEBAR_TCC),
            ("Meter",     METER_FIELDS),
            ("AMR",       AMR_FIELDS),
            ("Description",      [("Failure Description", "Failure Description")]),
            ("Corrective Action", [("Corrective Action",  "Corrective Action")]),
            ("Engineering Notes", [("Engineering Notes",  "Engineering Notes")]),
            ("TCC Comments",      [("TCC Comments",       "TCC Comments")]),
        ]

        def esc(v):
            if v is None:
                return ""
            s = str(v)
            if " " in s and any(c.isdigit() for c in s[:4]):
                s = s.split(" ")[0]
            return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        rows = ""
        for section, fields in all_sections:
            rows += (f'<tr><td colspan="2" style="background:#f0f0f0;padding:6px 8px;'
                     f'font-weight:bold;border-top:2px solid #bbb;">{section}</td></tr>\n')
            for label, key in fields:
                val = esc(self._report.get(key))
                rows += (f'<tr><td style="width:180px;padding:3px 8px;color:#555;'
                         f'white-space:nowrap;vertical-align:top;">{label}:</td>'
                         f'<td style="padding:3px 8px;vertical-align:top;">{val}</td></tr>\n')

        return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>body{{font-family:Arial,sans-serif;font-size:10pt;color:#222}}
h1{{font-size:14pt;margin-bottom:4px}}p{{margin:2px 0 10px;color:#666;font-size:9pt}}
table{{width:100%;border-collapse:collapse}}tr:nth-child(even) td{{background:#fafafa}}</style>
</head><body><h1>{esc(title)}</h1>
<p>Generated by FR Database Management System</p>
<table>{rows}</table></body></html>"""
