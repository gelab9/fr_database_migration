"""
New Report dialog — blank editable form for creating a new failure report.

Reuses field definitions and layout patterns from detail_view.py.
On Save, collects all field values and calls create_report() from db.queries.
[Index] is an identity column and is never included in the submitted dict.

Day 3 notes
-----------
Tab labels "Test & Failure" and "Review & Approval" are set as string
literals here (not derived from any variable), so .pyc caching cannot
cause them to revert to underscored names.  If you still see underscores
after pulling this file, delete __pycache__/ and ui/__pycache__/ and
restart the application.

Keyboard shortcuts added: Ctrl+S saves, Escape cancels.
"""

from PyQt6.QtCore import QDate, Qt
from PyQt6.QtGui import QFont, QKeySequence
from PyQt6.QtWidgets import (
    QComboBox,
    QDateEdit,
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

from db.queries import create_report, get_next_new_id
from ui.detail_view import (
    AMR_FIELDS,
    METER_FIELDS,
    MULTILINE_KEYS,
    REVIEW_FIELDS,
    TEST_FIELDS,
)


# ---------------------------------------------------------------------------
# Dropdown options
# ---------------------------------------------------------------------------

EUT_TYPE_OPTIONS = ["", "AMI", "Meter Only", "AMR Only", "OTHER EUT"]

TEST_TYPE_OPTIONS = [
    "", "EMC", "Reliability", "Functional", "Environmental",
    "Accuracy", "Mechanical", "Safety", "All", "Custom", "Past Tests",
]

METER_TYPE_OPTIONS = [
    "", "Revelo", "S4X Gen 2", "FOCUS AXe", "MAXsys", "FOCUS AX", "S4X",
    "S4X Gen 3", "FOCUS Axei", "FOCUS Axi", "FOCUS AX POLY", "FOCUS AL",
    "S4e", "Residential", "FOCUS", "AXEi", "Load Control Switch",
    "FOCUS AX EPS", "Focus Axe 8W", "DEV 2635", "PCB Board", "Prototype",
    "NextGenMeter", "AXe", "FOCUS AXe Gen 2", "FOCUS RXRe", "E360",
    "S4x RXR", "NA",
]

# DB keys → list of combo options (empty string = unset / blank)
COMBO_OPTIONS: dict[str, list[str]] = {
    "EUT_TYPE":   EUT_TYPE_OPTIONS,
    "Test Type":  TEST_TYPE_OPTIONS,
    "Meter Type": METER_TYPE_OPTIONS,
}

# DB keys that render as a NullableDateEdit
DATE_KEYS = {
    "Date Failed",
    "Date Closed",
    "Date Approved",
    "Date Corrected",
    "Failed_Sample_Ready_Date",
}


# ---------------------------------------------------------------------------
# NullableDateEdit
# ---------------------------------------------------------------------------

class NullableDateEdit(QWidget):
    """
    A QDateEdit paired with a clear button so the user can leave a date blank.

    Internally uses QDate(1900, 1, 1) as the null sentinel, displayed as
    "(none)" via setSpecialValueText.  get_value() returns None when null.
    """

    _NULL_DATE = QDate(1900, 1, 1)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._date_edit = QDateEdit()
        self._date_edit.setCalendarPopup(True)
        self._date_edit.setDisplayFormat("yyyy-MM-dd")
        self._date_edit.setMinimumDate(self._NULL_DATE)
        self._date_edit.setSpecialValueText("(none)")
        self._date_edit.setDate(self._NULL_DATE)   # start blank
        layout.addWidget(self._date_edit, stretch=1)

        self._clear_btn = QPushButton("✕")
        self._clear_btn.setFixedWidth(26)
        self._clear_btn.setToolTip("Clear date")
        self._clear_btn.clicked.connect(self._clear)
        layout.addWidget(self._clear_btn)

    def _clear(self):
        self._date_edit.setDate(self._NULL_DATE)

    def get_value(self):
        """Return the selected date as 'YYYY-MM-DD', or None if blank."""
        d = self._date_edit.date()
        if d == self._NULL_DATE:
            return None
        return d.toString("yyyy-MM-dd")

    def set_value(self, value):
        """Set the date from a 'YYYY-MM-DD' string or None."""
        if value is None:
            self._clear()
            return
        d = QDate.fromString(str(value)[:10], "yyyy-MM-dd")
        if d.isValid():
            self._date_edit.setDate(d)
        else:
            self._clear()


# ---------------------------------------------------------------------------
# New Report dialog
# ---------------------------------------------------------------------------

class NewReportDialog(QDialog):
    """
    Blank editable form for creating a new failure report.

    All fields start editable. Save calls create_report(); on success a
    confirmation box is shown with the assigned FR Index and the dialog closes.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._field_widgets: dict[str, QWidget] = {}

        try:
            self._next_new_id: int = get_next_new_id()
        except RuntimeError as e:
            QMessageBox.critical(None, "Database Error", str(e))
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, self.reject)
            return

        self.setWindowTitle("New Failure Report")
        self.resize(860, 700)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )

        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(12, 12, 12, 12)

        # ── Header ──────────────────────────────────────────────────────
        header_row = QHBoxLayout()

        title = QLabel("New Failure Report")
        title_font = QFont()
        title_font.setPointSize(13)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        header_row.addWidget(title)

        new_id_label = QLabel(f"New ID: {self._next_new_id}")
        new_id_label.setStyleSheet("color: #555; font-size: 10pt;")
        header_row.addWidget(new_id_label)

        self._save_btn = QPushButton("Save")
        self._save_btn.setFixedWidth(70)
        self._save_btn.setShortcut(QKeySequence("Ctrl+S"))
        self._save_btn.setToolTip("Save this report  (Ctrl+S)")
        self._save_btn.clicked.connect(self._on_save_clicked)
        header_row.addWidget(self._save_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedWidth(70)
        cancel_btn.clicked.connect(self.reject)
        header_row.addWidget(cancel_btn)

        root.addLayout(header_row)

        # ── Separator ───────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(sep)

        # ── Tabs ────────────────────────────────────────────────────────
        # NOTE: Tab labels are string literals here — do NOT replace with
        # variables. This ensures .pyc cache issues cannot affect the text.
        tabs = QTabWidget()
        root.addWidget(tabs)

        tabs.addTab(self._build_form_tab(METER_FIELDS),  "Meter Info")
        tabs.addTab(self._build_form_tab(AMR_FIELDS),    "AMR Info")
        tabs.addTab(self._build_form_tab(TEST_FIELDS),   "Test && Failure")
        tabs.addTab(self._build_form_tab(REVIEW_FIELDS), "Review && Approval")
        tabs.addTab(self._build_attachments_tab(),       "Attachments")

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
            label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if db_key in MULTILINE_KEYS:
                label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
                label.setContentsMargins(0, 4, 0, 0)

            form.addRow(label, widget)

        scroll.setWidget(container)
        return scroll

    def _make_field_widget(self, db_key: str) -> QWidget:
        if db_key in COMBO_OPTIONS:
            w = QComboBox()
            w.addItems(COMBO_OPTIONS[db_key])
            return w
        if db_key in DATE_KEYS:
            return NullableDateEdit()
        if db_key in MULTILINE_KEYS:
            w = QTextEdit()
            w.setFixedHeight(90)
            w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            return w
        return QLineEdit()

    def _build_attachments_tab(self) -> QWidget:
        """Tab 5 — informational only for new reports (no ID yet)."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        note = QLabel(
            "Attachments can be added after the report has been saved.\n\n"
            "Save this report first, then open it from the dashboard to manage attachments."
        )
        note.setAlignment(Qt.AlignmentFlag.AlignTop)
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()
        return container

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def _collect_fields(self) -> dict:
        """
        Gather every field widget value into a plain dict.

        [New ID] is always included — it is a required non-nullable int and
        must be present in every INSERT.  Its value was determined at dialog
        open time via get_next_new_id().

        [Index] is an identity column and is never included.

        All other keys with no value (empty string / null date) are omitted
        so SQL Server can apply column defaults instead of inserting NULL.
        """
        fields: dict = {"New ID": self._next_new_id}

        for db_key, widget in self._field_widgets.items():
            if isinstance(widget, QComboBox):
                val = widget.currentText().strip() or None
            elif isinstance(widget, NullableDateEdit):
                val = widget.get_value()
            elif isinstance(widget, QTextEdit):
                val = widget.toPlainText().strip() or None
            else:  # QLineEdit
                val = widget.text().strip() or None

            if val is not None:
                fields[db_key] = val

        return fields

    def _on_save_clicked(self):
        fields = self._collect_fields()

        new_index = create_report(fields)
        if new_index is not None:
            QMessageBox.information(
                self,
                "Created",
                f"Report created successfully.\nFR Index: {new_index}  |  New ID: {self._next_new_id}",
            )
            self.accept()
        else:
            QMessageBox.critical(
                self,
                "Create Failed",
                "Save failed — please try again.",
            )

    # ------------------------------------------------------------------
    # Keyboard
    # ------------------------------------------------------------------

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
        else:
            super().keyPressEvent(event)


# ---------------------------------------------------------------------------
# Convenience helper (called from main.py)
# ---------------------------------------------------------------------------

def open_new_report(parent=None) -> NewReportDialog:
    """Create and exec a NewReportDialog; return the dialog instance."""
    dlg = NewReportDialog(parent=parent)
    dlg.exec()
    return dlg