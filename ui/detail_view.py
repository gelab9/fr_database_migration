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

from db.queries import delete_report, fetch_attachments_by_new_id, fetch_report_by_id, update_report


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

        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setObjectName("delete_btn")
        self._delete_btn.setFixedWidth(70)
        self._delete_btn.setToolTip("Permanently delete this report")
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

        self._tabs.addTab(self._build_form_tab(METER_FIELDS),  "Meter Info")
        self._tabs.addTab(self._build_form_tab(AMR_FIELDS),    "AMR Info")
        self._tabs.addTab(self._build_form_tab(TEST_FIELDS),   "Test && Failure")
        self._tabs.addTab(self._build_form_tab(REVIEW_FIELDS), "Review && Approval")
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

        # Inline attachments field (from the main table)
        inline_label = QLabel("Attachments field (from report):")
        inline_label.setFont(QFont("", -1, QFont.Weight.Bold))
        layout.addWidget(inline_label)

        self._attachments_field = QTextEdit()
        self._attachments_field.setReadOnly(True)
        self._attachments_field.setFixedHeight(80)
        layout.addWidget(self._attachments_field)

        # ATTACHMENT table rows
        self._attachment_info = QLabel()
        self._attachment_info.setWordWrap(True)
        layout.addWidget(self._attachment_info)

        layout.addStretch()
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
            else:
                widget.setText(text)

        # Attachments tab
        inline_val = self._report.get("Attachments")
        self._attachments_field.setPlainText(
            "" if inline_val is None else str(inline_val)
        )

        new_id_val = self._report.get("New ID")
        if new_id_val is not None:
            try:
                rows = fetch_attachments_by_new_id(int(new_id_val))
                if rows:
                    self._attachment_info.setText(
                        f"{len(rows)} attachment record(s) found in the ATTACHMENT table "
                        f"for New ID {new_id_val}."
                    )
                else:
                    self._attachment_info.setText(
                        f"No attachment records found in the ATTACHMENT table "
                        f"for New ID {new_id_val}."
                    )
            except Exception as e:
                self._attachment_info.setText(f"Error querying attachments: {e}")
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
        fields = {}
        for db_key, widget in self._field_widgets.items():
            if isinstance(widget, QTextEdit):
                fields[db_key] = widget.toPlainText() or None
            elif isinstance(widget, QLineEdit):
                text = widget.text().strip()
                fields[db_key] = text or None

        self.save_requested.emit(self._index, fields)

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
            ("Test & Failure",    TEST_FIELDS),
            ("Review & Approval", REVIEW_FIELDS),
        ]

        def esc(v):
            if v is None:
                return ""
            s = str(v)
            # Strip time from dates
            if " " in s and any(c.isdigit() for c in s[:4]):
                s = s.split(" ")[0]
            return (s
                    .replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;"))

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

def open_detail(index: int, parent=None, on_deleted=None):
    """
    Create a DetailDialog, wire save_requested → update_report, and exec.

    Parameters
    ----------
    on_deleted : callable | None
        Optional zero-argument callback invoked if the report is deleted
        inside the dialog (so the caller can refresh its list).
    """
    dlg = DetailDialog(index, parent=parent)

    def _on_save(idx: int, fields: dict):
        success = update_report(idx, fields)
        dlg.handle_save_result(success)

    dlg.save_requested.connect(_on_save)

    if on_deleted is not None:
        dlg.report_deleted.connect(lambda _idx: on_deleted())

    dlg.exec()
    return dlg