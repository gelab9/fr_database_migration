"""
Detail view dialog — displays all 70 columns for a single failure report
in a 5-tab read-only layout.

Opens from the dashboard on row double-click. Receives the [Index] PK,
fetches via fetch_report_by_id(), and populates each tab. The Edit button
toggles all fields to editable; save logic is connected externally via the
save_requested signal.
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from db.queries import fetch_attachments_by_new_id, fetch_report_by_id, update_report


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

TEST_FIELDS = [
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
    ("Failure Description", "Failure Description"),
    ("Corrective Action",   "Corrective Action"),
    ("Engineering Notes",   "Engineering Notes"),
]

REVIEW_FIELDS = [
    ("TCC 1",                   "TCC 1"),
    ("TCC 2",                   "TCC 2"),
    ("TCC 3",                   "TCC 3"),
    ("TCC 4",                   "TCC 4"),
    ("TCC 5",                   "TCC 5"),
    ("TCC 6",                   "TCC 6"),
    ("TCC Comments",            "TCC Comments"),
    ("TCC Review Required",     "TCC_Review_Required"),
    ("FR Ready For Review",     "FR_Ready_For_Review"),
    ("FR Approved",             "FR_Approved"),
    ("Approved By",             "Approved By"),
    ("Date Approved",           "Date Approved"),
    ("Date Closed",             "Date Closed"),
    ("Corrected By",            "Corrected By"),
    ("Date Corrected",          "Date Corrected"),
    ("Pass",                    "Pass"),
    ("Anomaly",                 "Anomaly"),
    ("Failed Sample Ready",     "Failed_Sample_Ready"),
    ("Failed Sample Ready Date","Failed_Sample_Ready_Date"),
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
        name to its current widget value.  Wire this to update_report()
        in the next step.
    """

    save_requested = pyqtSignal(int, dict)

    def __init__(self, index: int, parent=None):
        super().__init__(parent)
        self._index = index
        self._editing = False
        # Maps db key → QWidget (QLineEdit or QTextEdit)
        self._field_widgets: dict[str, QWidget] = {}

        self.setWindowTitle("Failure Report Detail")
        self.resize(860, 700)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )

        self._report = fetch_report_by_id(index)
        if self._report is None:
            QMessageBox.critical(self, "Error", f"Report with Index {index} not found.")
            # Defer close until after __init__ returns
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, self.reject)
            return

        self._build_ui()
        self._populate()

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

        self._edit_btn = QPushButton("Edit")
        self._edit_btn.setFixedWidth(70)
        self._edit_btn.clicked.connect(self._on_edit_clicked)
        header_row.addWidget(self._edit_btn)

        self._save_btn = QPushButton("Save")
        self._save_btn.setFixedWidth(70)
        self._save_btn.setVisible(False)
        self._save_btn.clicked.connect(self._on_save_clicked)
        header_row.addWidget(self._save_btn)

        self._close_btn = QPushButton("Close")
        self._close_btn.setFixedWidth(70)
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

        self._tabs.addTab(self._build_form_tab(METER_FIELDS),  "Meter Info")
        self._tabs.addTab(self._build_form_tab(AMR_FIELDS),    "AMR Info")
        self._tabs.addTab(self._build_form_tab(TEST_FIELDS),   "Test & Failure")
        self._tabs.addTab(self._build_form_tab(REVIEW_FIELDS), "Review & Approval")
        self._tabs.addTab(self._build_attachments_tab(),       "Attachments")

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
            # Align label to top for multiline fields
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
            w.setFixedHeight(90)
            w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            return w
        else:
            w = QLineEdit()
            w.setReadOnly(True)
            return w

    def _build_attachments_tab(self) -> QWidget:
        """Tab 5 — shows the Attachments field from the main table and
        the count of rows in the ATTACHMENT table for this report."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # ── Attachments field from the main FR table ────────────────────
        main_label = QLabel("Attachments field (from Failure Report table):")
        main_label.setFont(QFont("", -1, QFont.Weight.Bold))
        layout.addWidget(main_label)

        self._attachments_field = QLineEdit()
        self._attachments_field.setReadOnly(True)
        self._field_widgets["Attachments"] = self._attachments_field
        layout.addWidget(self._attachments_field)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep)

        # ── ATTACHMENT table rows ───────────────────────────────────────
        att_header = QLabel("ATTACHMENT table records:")
        att_header.setFont(QFont("", -1, QFont.Weight.Bold))
        layout.addWidget(att_header)

        self._attachment_info = QLabel("Loading…")
        self._attachment_info.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._attachment_info.setWordWrap(True)
        layout.addWidget(self._attachment_info)

        layout.addStretch()
        return container

    # ------------------------------------------------------------------
    # Data population
    # ------------------------------------------------------------------

    def _populate(self):
        new_id  = self._report.get("New ID",  "")
        project = self._report.get("Project", "")
        self._title_label.setText(
            f"FR {new_id}   —   {project}" if project else f"FR {new_id}"
        )

        for db_key, widget in self._field_widgets.items():
            if db_key == "Attachments":
                continue  # handled below
            raw = self._report.get(db_key)
            text = "" if raw is None else str(raw)
            # Strip time component from datetime values
            if "Date" in db_key and " " in text:
                text = text.split(" ")[0]
            if isinstance(widget, QTextEdit):
                widget.setPlainText(text)
            else:
                widget.setText(text)

        # Main table Attachments field
        raw_att = self._report.get("Attachments")
        self._attachments_field.setText("" if raw_att is None else str(raw_att))

        # ATTACHMENT table rows
        new_id_val = self._report.get("New ID")
        if new_id_val is not None:
            att_rows = fetch_attachments_by_new_id(int(new_id_val))
            if att_rows:
                lines = [f"  ID {r['ID']}  (FR_ID: {r['FR_ID']})" for r in att_rows]
                self._attachment_info.setText(
                    f"{len(att_rows)} attachment(s) found:\n" + "\n".join(lines)
                )
            else:
                self._attachment_info.setText("No attachments in ATTACHMENT table.")
        else:
            self._attachment_info.setText("Unable to query attachments — New ID not set.")

    # ------------------------------------------------------------------
    # Edit / save toggle
    # ------------------------------------------------------------------

    def _set_editable(self, editable: bool):
        """Toggle all field widgets between read-only and editable."""
        self._editing = editable

        for db_key, widget in self._field_widgets.items():
            if isinstance(widget, QTextEdit):
                widget.setReadOnly(not editable)
            elif isinstance(widget, QLineEdit):
                widget.setReadOnly(not editable)

        # Swap button states
        self._edit_btn.setText("Cancel" if editable else "Edit")
        self._save_btn.setVisible(editable)

        # Switch stylesheet so read-only fields look right in each mode
        self.setStyleSheet(_EDITABLE_STYLE if editable else _READONLY_STYLE)

    def _on_edit_clicked(self):
        if self._editing:
            # Cancel — repopulate from original data and go back to read-only
            self._populate()
            self._set_editable(False)
        else:
            self._set_editable(True)

    def _on_save_clicked(self):
        """Collect all field values and emit save_requested.
        The connected handler calls update_report() and then calls
        handle_save_result() to show feedback and toggle the mode."""
        fields = {}
        for db_key, widget in self._field_widgets.items():
            if isinstance(widget, QTextEdit):
                fields[db_key] = widget.toPlainText() or None
            elif isinstance(widget, QLineEdit):
                text = widget.text().strip()
                fields[db_key] = text or None

        self.save_requested.emit(self._index, fields)

    def handle_save_result(self, success: bool):
        """Called by the save_requested handler after update_report() returns.

        On success: shows confirmation, switches back to read-only.
        On failure: shows error, stays in edit mode so the user can retry.
        """
        if success:
            QMessageBox.information(
                self, "Saved", "Report saved successfully."
            )
            self._set_editable(False)
        else:
            QMessageBox.critical(
                self, "Save Failed", "Save failed — please try again."
            )


# ---------------------------------------------------------------------------
# Wire detail view into the dashboard (helper used by main.py / dashboard)
# ---------------------------------------------------------------------------

def open_detail(index: int, parent=None):
    """Create a DetailDialog, wire save_requested → update_report, and exec."""
    dlg = DetailDialog(index, parent=parent)

    def _on_save(idx: int, fields: dict):
        success = update_report(idx, fields)
        dlg.handle_save_result(success)

    dlg.save_requested.connect(_on_save)
    dlg.exec()
    return dlg
