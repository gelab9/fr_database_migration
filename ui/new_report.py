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

from db.lookup_queries import (
    fetch_amr_models,
    fetch_amr_manufacturers,
    fetch_amr_types,
    fetch_amr_subtypes,
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
from db.queries import create_report, fetch_distinct_column_values, get_next_new_id
from ui.matrix_import import MatrixImportDialog
from ui.detail_view import (
    AMR_FIELDS,
    ENGINEERING_FIELDS,
    FAILURE_FIELDS,
    LARGE_MULTILINE_KEYS,
    METER_FIELDS,
    MULTILINE_KEYS,
    REVIEW_FIELDS,
    TEST_INFO_FIELDS,
)


# ---------------------------------------------------------------------------
# Dropdown options
# ---------------------------------------------------------------------------

EUT_TYPE_OPTIONS = ["", "AMI", "Meter Only", "AMR Only", "OTHER EUT"]

# Static fallbacks used when the METER_SPECS DB is unavailable
_FALLBACK_TEST_TYPES = [
    "", "EMC", "Reliability", "Functional", "Environmental",
    "Accuracy", "Mechanical", "Safety", "Custom", "Past Tests",
]

# AMR subtype values that must always appear in the dropdown regardless of
# what is currently in the METER_SPECS DB (pending SQL migration run).
_REQUIRED_AMR_SUBTYPES = ["Mesh", "Mesh IP", "Series 4", "Series 5", "Series 6"]


def _load_combined_meter_subtypes() -> list[str]:
    """Combined Meter Type + SubType options — used for Sub Type, Sub Type II."""
    types    = fetch_meter_types()
    subtypes = fetch_meter_subtypes()
    combined = sorted(set(types + subtypes), key=str.casefold)
    return [""] + combined


def _load_combined_amr_subtypes() -> list[str]:
    """Combined AMR Type + SubType options — used for Sub Type, Sub Type II, Sub Type III."""
    types    = fetch_amr_types()
    subtypes = fetch_amr_subtypes()
    combined = sorted(
        set(types + subtypes + _REQUIRED_AMR_SUBTYPES),
        key=str.casefold,
    )
    return [""] + combined

# DB keys whose combo items are loaded from METER_SPECS at form-open time.
# Value is a callable () -> list[str].  An empty string is prepended so the
# field can be left blank, matching VB behaviour.
_DB_COMBO_LOADERS: dict[str, callable] = {
    "EUT_TYPE":              lambda: EUT_TYPE_OPTIONS,
    "Project_Number":        lambda: [""] + [
                                 "N/A" if v.strip().lower() == "na" else v
                                 for v in fetch_distinct_column_values("Project_Number")
                             ],
    "Test_Type":             lambda: [""] + (fetch_test_types() or _FALLBACK_TEST_TYPES[1:]),
    "Level":                 lambda: [""] + fetch_test_levels(),
    "Test":                  lambda: [""] + fetch_test_names(),
    "Tested By":             lambda: [""] + fetch_testers(),
    "Assigned To":           lambda: [""] + fetch_testers(),
    "Meter":                 lambda: [""] + fetch_meter_models(),
    "Meter_Manufacturer":    lambda: [""] + fetch_meter_manufacturers(),
    "Meter_Type":            lambda: [""] + fetch_meter_types(),
    "Meter_SubType":         _load_combined_meter_subtypes,
    "Meter_SubTypeII":       _load_combined_meter_subtypes,
    "Form":                  lambda: [""] + fetch_meter_forms(),
    "Meter_Base":            lambda: [""] + fetch_meter_bases(),
    "AMR":                   lambda: [""] + fetch_amr_models(),
    "AMR_Manufacturer":      lambda: [""] + fetch_amr_manufacturers(),
    "AMR_Type":              lambda: [""] + fetch_amr_types(),
    "AMR_SUBType":           _load_combined_amr_subtypes,
    "AMR_SUBTypeII":         _load_combined_amr_subtypes,
    "AMR_SUBTypeIII":        _load_combined_amr_subtypes,
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
        self._date_edit.setDisplayFormat("MM/dd/yyyy")
        self._date_edit.setMinimumDate(self._NULL_DATE)
        self._date_edit.setSpecialValueText("(none)")
        self._date_edit.setDate(self._NULL_DATE)   # default to blank
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

        import_btn = QPushButton("Import from Matrix")
        import_btn.setObjectName("outline_btn")
        import_btn.setToolTip(
            "Pre-fill this form from a Matrix spreadsheet on the HQA drive"
        )
        import_btn.clicked.connect(self._on_import_matrix)
        header_row.addWidget(import_btn)

        self._save_btn = QPushButton("Save")
        self._save_btn.setObjectName("save_btn")
        self._save_btn.setFixedWidth(70)
        self._save_btn.setShortcut(QKeySequence("Ctrl+S"))
        self._save_btn.setToolTip("Save this report  (Ctrl+S)")
        self._save_btn.clicked.connect(self._on_save_clicked)
        header_row.addWidget(self._save_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("cancel_btn")
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

        tabs.addTab(self._build_form_tab(METER_FIELDS),        "Meter Info")
        tabs.addTab(self._build_form_tab(AMR_FIELDS),          "AMR Info")
        tabs.addTab(QWidget(),                                 "WIFI")
        tabs.addTab(self._build_form_tab(TEST_INFO_FIELDS),    "Test Info")
        tabs.addTab(self._build_form_tab(FAILURE_FIELDS),      "Failure")
        tabs.addTab(self._build_form_tab(ENGINEERING_FIELDS),  "Engineering")
        tabs.addTab(self._build_form_tab(REVIEW_FIELDS),       "Review && Approval")
        tabs.addTab(self._build_attachments_tab(),             "Attachments")

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
        if db_key in _DB_COMBO_LOADERS:
            w = QComboBox()
            w.setEditable(True)   # mirrors VB: user can type a custom value
            w.addItems(_DB_COMBO_LOADERS[db_key]())
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

    # ------------------------------------------------------------------
    # Matrix import
    # ------------------------------------------------------------------

    def _on_import_matrix(self):
        """Open the Matrix import dialog and pre-fill form fields."""
        dlg = MatrixImportDialog(self)
        if dlg.exec() != MatrixImportDialog.DialogCode.Accepted:
            return
        data = dlg.get_mapped_fields()
        self._prefill_from_dict(data)
        filled = len(data)
        QMessageBox.information(
            self,
            "Import Complete",
            f"{filled} field(s) pre-filled from the Matrix spreadsheet.\n\n"
            "Review each tab and adjust any values before saving.",
        )

    def _prefill_from_dict(self, data: dict):
        """Set form field values from a dict of FR db_key → str value."""
        for db_key, value in data.items():
            widget = self._field_widgets.get(db_key)
            if widget is None:
                continue
            if isinstance(widget, QComboBox):
                idx = widget.findText(value, Qt.MatchFlag.MatchFixedString)
                if idx >= 0:
                    widget.setCurrentIndex(idx)
                else:
                    widget.setCurrentText(value)
            elif isinstance(widget, NullableDateEdit):
                widget.set_value(value)
            elif isinstance(widget, QTextEdit):
                widget.setPlainText(value)
            else:
                widget.setText(value)

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
        # Always seed these boolean fields so the VB app's open-report filter
        # (WHERE [FR_Approved] <> 'Checked') and Python's open_only filter both
        # see new reports correctly.  NULL is treated as neither Checked nor
        # Unchecked by SQL Server comparison, so rows would disappear from both
        # "open" and "closed" views if left NULL.
        fields: dict = {
            "New ID":      self._next_new_id,
            "Pass":        "Unchecked",
            "FR_Approved": "Unchecked",
            "Anomaly":     "Unchecked",
        }

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
        reply = QMessageBox.question(
            self,
            "Create Report",
            "Are you sure you want to create this report?\n\n"
            "This will permanently add the report to the database.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

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