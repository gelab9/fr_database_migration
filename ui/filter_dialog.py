"""
Advanced Filter dialog — mirrors frmFilter.vb.

Each combo's Tag maps to the exact SQL column name in [Failure Report].
Filter is built as a raw SQL WHERE string (matching VB BindingSource.Filter
behaviour) and passed to search_with_filter() in db/queries.py.

Sections
--------
- General   : EUT Type, Test Type/Name/Level, Project, Assigned To, etc.
- Meter     : all Meter EUT fields (cbMeterBase / cbMeterForm are a special pair)
- AMR       : all AMR EUT fields
- Date ranges : Date Failed / Corrected / Approved / Closed (each with AND/OR)
- New ID range
- Report category : All / Anomaly / Failure
- Ready For Review : per-level checkboxes (PAC1/PAC2/CIT/FPA/ENG/OEM)
                     plus All-Ready and Open-Only and Transferred-Only
- Preserve filter : combine new filter with previous via AND/OR
- SQL preview pane
"""

from PyQt6.QtCore import QDate, Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from db.queries import fetch_distinct_column_values, search_with_filter


# ---------------------------------------------------------------------------
# Field definitions  (label, db_column_tag)
# The Form/Base meter pair is defined separately and handled specially in
# _build_filter() — matching VB's special-case block exactly.
# ---------------------------------------------------------------------------

_GENERAL_FIELDS: list[tuple[str, str]] = [
    ("EUT Type",       "EUT_Type"),
    ("Test Type",      "Test_Type"),
    ("Test Name",      "Test"),
    ("Test Level",     "Level"),
    ("Project Name",   "PROJECT"),
    ("Project Number", "Project_Number"),
    ("Assigned To",    "Assigned To"),
    ("Corrected By",   "Corrected By"),
    ("Approved By",    "Approved By"),
]

_METER_FIELDS: list[tuple[str, str]] = [
    ("Meter Model",   "Meter"),
    ("Manufacturer",  "Meter_Manufacturer"),
    ("Meter Type",    "Meter_Type"),
    ("Sub Type",      "Meter_SubType"),
    ("Sub Type II",   "Meter_SubTypeII"),
    ("Voltage",       "Meter_SubType"),    # VB: cbMeterVoltage.Tag = "Meter_SubType"
    ("Serial Number", "Meter_Serial_Number"),
    ("DSP Rev",       "Meter_DSP_REV"),
    ("FW Version",    "FW Ver"),
    ("PCBA",          "Meter_PCBA"),
    ("PCBA Rev",      "Meter_PCBA_Rev"),
    ("Software",      "Meter_Software"),
    ("Software Rev",  "Meter_Software_REv"),
]

_AMR_FIELDS: list[tuple[str, str]] = [
    ("AMR Model",    "AMR"),
    ("Manufacturer", "AMR_Manufacturer"),
    ("AMR Type",     "AMR_Type"),
    ("Sub Type",     "AMR_SubType"),
    ("Sub Type II",  "AMR_SubTypeII"),
    ("Sub Type III", "AMR_SubTypeIII"),
    ("Serial Number","AMR_SN"),
    ("IP/LAN ID",    "AMR_IP_LAN_ID"),
    ("FW Rev",       "AMR Rev"),
    ("PCBA P/N",     "AMR_PCBA"),
    ("PCBA Rev",     "AMR_PCBA_Rev"),
    ("Software",     "AMR_Software"),
    ("Software Rev", "AMR_Software_Rev"),
    ("Voltage",      "AMR_Voltage"),
]


# ---------------------------------------------------------------------------
# NullableDateEdit (local copy — avoids import cycle with new_report)
# ---------------------------------------------------------------------------

class _NullableDateEdit(QWidget):
    _NULL_DATE = QDate(1900, 1, 1)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        self._de = QDateEdit()
        self._de.setCalendarPopup(True)
        self._de.setDisplayFormat("yyyy-MM-dd")
        self._de.setMinimumDate(self._NULL_DATE)
        self._de.setSpecialValueText("(none)")
        self._de.setDate(self._NULL_DATE)
        lay.addWidget(self._de, stretch=1)

        btn = QPushButton("✕")
        btn.setFixedWidth(26)
        btn.setToolTip("Clear date")
        btn.clicked.connect(self._clear)
        lay.addWidget(btn)

    def _clear(self):
        self._de.setDate(self._NULL_DATE)

    def is_set(self) -> bool:
        return self._de.date() != self._NULL_DATE

    def get_value(self) -> str:
        """Return 'YYYY-MM-DD' string (only call when is_set() is True)."""
        return self._de.date().toString("yyyy-MM-dd")


# ---------------------------------------------------------------------------
# Filter Dialog
# ---------------------------------------------------------------------------

class FilterDialog(QDialog):
    """
    Advanced filter dialog — matches frmFilter.vb layout and build logic.

    Usage::

        dlg = FilterDialog(parent=win)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            rows = dlg.result_rows   # list[dict] from search_with_filter()
            clause = dlg.result_clause  # raw WHERE string
    """

    def __init__(self, initial_clause: str = "", parent=None):
        super().__init__(parent)
        self.result_rows: list[dict] = []
        self.result_clause: str = ""

        self._initial_clause = initial_clause

        # Storage for each filter section:
        # _combo_rows: list of (db_col, QComboBox, and_or_QCheckBox)
        self._general_rows:  list[tuple[str, QComboBox, QCheckBox]] = []
        self._meter_rows:    list[tuple[str, QComboBox, QCheckBox]] = []
        self._amr_rows:      list[tuple[str, QComboBox, QCheckBox]] = []

        # Special meter pair
        self._meter_form_combo: QComboBox | None = None
        self._meter_form_check: QCheckBox | None = None  # AND/OR for form pair
        self._meter_base_combo: QComboBox | None = None

        self.setWindowTitle("Advanced Filter")
        self.resize(820, 780)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        self._build_ui()
        if initial_clause:
            self._sql_preview.setPlainText(initial_clause)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(10, 10, 10, 10)

        # ── Tabs: General / Meter / AMR ─────────────────────────────────
        tabs = QTabWidget()
        tabs.addTab(self._build_combo_tab(_GENERAL_FIELDS, self._general_rows, "general"),
                    "General")
        tabs.addTab(self._build_combo_tab(_METER_FIELDS,   self._meter_rows,   "meter"),
                    "Meter")
        tabs.addTab(self._build_combo_tab(_AMR_FIELDS,     self._amr_rows,     "amr"),
                    "AMR")
        root.addWidget(tabs)

        # ── Date ranges ─────────────────────────────────────────────────
        root.addWidget(self._build_date_ranges())

        # ── New ID range + Report category ──────────────────────────────
        mid_row = QHBoxLayout()
        mid_row.addWidget(self._build_new_id_range())
        mid_row.addWidget(self._build_report_category())
        mid_row.addWidget(self._build_ready_for_review())
        root.addLayout(mid_row)

        # ── Preserve filter ─────────────────────────────────────────────
        preserve_row = QHBoxLayout()
        self._chk_preserve = QCheckBox("Preserve existing filter")
        preserve_row.addWidget(self._chk_preserve)
        self._chk_preserve_and_or = QCheckBox("Use OR (default: AND)")
        self._chk_preserve_and_or.setToolTip(
            "Checked = combine with OR; unchecked = combine with AND"
        )
        preserve_row.addWidget(self._chk_preserve_and_or)
        preserve_row.addStretch()
        root.addLayout(preserve_row)

        # ── SQL preview ─────────────────────────────────────────────────
        root.addWidget(QLabel("Filter (WHERE clause):"))
        self._sql_preview = QTextEdit()
        self._sql_preview.setFixedHeight(70)
        self._sql_preview.setPlaceholderText("(no filter — returns all records)")
        root.addWidget(self._sql_preview)

        # ── Buttons ─────────────────────────────────────────────────────
        btn_row = QHBoxLayout()

        build_btn = QPushButton("Build Filter")
        build_btn.setToolTip("Assemble WHERE clause from selections above")
        build_btn.clicked.connect(self._on_build_clicked)
        btn_row.addWidget(build_btn)

        apply_btn = QPushButton("Apply / Search")
        apply_btn.setDefault(True)
        apply_btn.clicked.connect(self._on_apply_clicked)
        btn_row.addWidget(apply_btn)

        reset_btn = QPushButton("Reset")
        reset_btn.clicked.connect(self._on_reset_clicked)
        btn_row.addWidget(reset_btn)

        btn_row.addStretch()

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(close_btn)

        root.addLayout(btn_row)

    # ------------------------------------------------------------------

    def _build_combo_tab(
        self,
        field_defs: list[tuple[str, str]],
        row_store: list,
        panel: str,
    ) -> QScrollArea:
        """
        Build a scrollable form tab for one panel's combo fields.
        Each row: label | [EMPTY] + distinct-value combo | AND/OR checkbox
        row_store is populated with (db_col, combo, and_or_check) tuples.
        """
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        form = QFormLayout(container)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(5)
        form.setContentsMargins(10, 10, 10, 10)

        for label_text, db_col in field_defs:
            combo = QComboBox()
            combo.setEditable(True)
            combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            # Items loaded lazily when user clicks the dropdown (see _on_combo_about_to_show)
            # Pre-load "[EMPTY]" + blank so the combo is usable immediately.
            combo.addItems(["", "[EMPTY]"])
            combo.setCurrentIndex(0)

            and_or_chk = QCheckBox("OR")
            and_or_chk.setToolTip("Checked = OR with previous condition; unchecked = AND")

            row_store.append((db_col, combo, and_or_chk))

            field_row = QHBoxLayout()
            field_row.addWidget(combo, stretch=1)
            field_row.addWidget(and_or_chk)
            w = QWidget()
            w.setLayout(field_row)
            form.addRow(QLabel(label_text + ":"), w)

        # Meter tab: add Form + Base special pair at the bottom
        if panel == "meter":
            self._meter_form_check = QCheckBox("OR")
            self._meter_form_check.setToolTip("AND/OR for the Form+Base pair")

            self._meter_form_combo = QComboBox()
            self._meter_form_combo.setEditable(True)
            self._meter_form_combo.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
            self._meter_form_combo.addItems(["", "[EMPTY]"])

            self._meter_base_combo = QComboBox()
            self._meter_base_combo.setEditable(True)
            self._meter_base_combo.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
            self._meter_base_combo.addItems(["", "[EMPTY]"])

            form_base_row = QHBoxLayout()
            form_base_row.addWidget(QLabel("Form:"))
            form_base_row.addWidget(self._meter_form_combo, stretch=1)
            form_base_row.addWidget(QLabel("Base:"))
            form_base_row.addWidget(self._meter_base_combo, stretch=1)
            form_base_row.addWidget(self._meter_form_check)
            w2 = QWidget()
            w2.setLayout(form_base_row)
            form.addRow(QLabel("Form / Base:"), w2)

        scroll.setWidget(container)

        # Populate combos on first show (lazy)
        scroll.setProperty("_panel", panel)
        scroll.setProperty("_populated", False)
        scroll.installEventFilter(self)

        return scroll

    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        if (
            event.type() == QEvent.Type.Show
            and hasattr(obj, "property")
            and obj.property("_panel") is not None
            and not obj.property("_populated")
        ):
            self._populate_tab_combos(obj.property("_panel"))
            obj.setProperty("_populated", True)
        return super().eventFilter(obj, event)

    def _populate_tab_combos(self, panel: str):
        if panel == "general":
            rows = self._general_rows
            extra = []
        elif panel == "meter":
            rows = self._meter_rows
            extra = [
                (self._meter_form_combo, "Form"),
                (self._meter_base_combo, "Meter_Base"),
            ]
        else:
            rows = self._amr_rows
            extra = []

        for db_col, combo, _ in rows:
            self._fill_combo(combo, db_col)
        for combo, db_col in extra:
            self._fill_combo(combo, db_col)

    @staticmethod
    def _fill_combo(combo: QComboBox, db_col: str):
        current = combo.currentText()
        combo.blockSignals(True)
        combo.clear()
        items = ["", "[EMPTY]"] + fetch_distinct_column_values(db_col)
        combo.addItems(items)
        idx = combo.findText(current)
        combo.setCurrentIndex(max(0, idx))
        combo.blockSignals(False)

    # ------------------------------------------------------------------

    def _build_date_ranges(self) -> QGroupBox:
        gb = QGroupBox("Date Ranges")
        layout = QFormLayout(gb)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(4)

        def _date_row(label: str):
            """Return (from_widget, to_widget, and_or_chk, row_widget)."""
            from_w = _NullableDateEdit()
            to_w = _NullableDateEdit()
            and_or = QCheckBox("OR")
            and_or.setToolTip("OR (unchecked = AND) with preceding conditions")
            row = QHBoxLayout()
            row.setSpacing(4)
            row.addWidget(QLabel("From:"))
            row.addWidget(from_w, stretch=1)
            row.addWidget(QLabel("To:"))
            row.addWidget(to_w, stretch=1)
            row.addWidget(and_or)
            w = QWidget()
            w.setLayout(row)
            return from_w, to_w, and_or, w

        self._df_from, self._df_to, self._df_and_or, w1 = _date_row("Date Failed")
        self._dc_from, self._dc_to, self._dc_and_or, w2 = _date_row("Date Corrected")
        self._da_from, self._da_to, self._da_and_or, w3 = _date_row("Date Approved")
        self._dcl_from, self._dcl_to, self._dcl_and_or, w4 = _date_row("Date Closed")

        layout.addRow(QLabel("Date Failed:"),    w1)
        layout.addRow(QLabel("Date Corrected:"), w2)
        layout.addRow(QLabel("Date Approved:"),  w3)
        layout.addRow(QLabel("Date Closed:"),    w4)
        return gb

    def _build_new_id_range(self) -> QGroupBox:
        gb = QGroupBox("New ID Range")
        lay = QFormLayout(gb)
        self._new_id_from = QLineEdit()
        self._new_id_from.setPlaceholderText("from")
        self._new_id_from.setFixedWidth(80)
        self._new_id_to = QLineEdit()
        self._new_id_to.setPlaceholderText("to")
        self._new_id_to.setFixedWidth(80)
        row = QHBoxLayout()
        row.addWidget(self._new_id_from)
        row.addWidget(QLabel("–"))
        row.addWidget(self._new_id_to)
        row.addStretch()
        w = QWidget()
        w.setLayout(row)
        lay.addRow(QLabel("New ID:"), w)
        return gb

    def _build_report_category(self) -> QGroupBox:
        gb = QGroupBox("Report Category")
        lay = QVBoxLayout(gb)
        self._rb_all     = QRadioButton("All")
        self._rb_anomaly = QRadioButton("Anomaly")
        self._rb_failure = QRadioButton("Failure")
        self._rb_all.setChecked(True)
        lay.addWidget(self._rb_all)
        lay.addWidget(self._rb_anomaly)
        lay.addWidget(self._rb_failure)
        lay.addStretch()
        return gb

    def _build_ready_for_review(self) -> QGroupBox:
        gb = QGroupBox("Ready For Review")
        lay = QVBoxLayout(gb)

        self._chk_rfr_disable = QCheckBox("Disable (ignore this section)")
        self._chk_rfr_disable.setChecked(True)
        self._chk_rfr_disable.stateChanged.connect(self._on_rfr_disable_changed)
        lay.addWidget(self._chk_rfr_disable)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        lay.addWidget(sep)

        self._chk_tcc_required = QCheckBox("TCC Review Required")
        lay.addWidget(self._chk_tcc_required)

        self._chk_pac1 = QCheckBox("PAC 1")
        self._chk_pac2 = QCheckBox("PAC 2")
        self._chk_cit  = QCheckBox("CIT")
        self._chk_fpa  = QCheckBox("FPA")
        self._chk_eng  = QCheckBox("ENG")
        self._chk_oem  = QCheckBox("OEM")
        for c in (self._chk_pac1, self._chk_pac2, self._chk_cit,
                  self._chk_fpa, self._chk_eng, self._chk_oem):
            c.setEnabled(False)
            lay.addWidget(c)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        lay.addWidget(sep2)

        self._rb_rfr_all_ready = QRadioButton("All Ready for Review")
        self._rb_rfr_all_ready.setEnabled(False)
        lay.addWidget(self._rb_rfr_all_ready)

        self._chk_open_only       = QCheckBox("Open reports only")
        self._chk_transferred     = QCheckBox("Transferred reports only")
        for c in (self._chk_open_only, self._chk_transferred):
            c.setEnabled(False)
            lay.addWidget(c)

        lay.addStretch()
        return gb

    def _on_rfr_disable_changed(self, state: int):
        enabled = (state != Qt.CheckState.Checked.value)
        for w in (
            self._chk_tcc_required,
            self._chk_pac1, self._chk_pac2, self._chk_cit,
            self._chk_fpa, self._chk_eng, self._chk_oem,
            self._rb_rfr_all_ready,
            self._chk_open_only, self._chk_transferred,
        ):
            w.setEnabled(enabled)

    # ------------------------------------------------------------------
    # Filter building — mirrors Filter_BuildFilter() exactly
    # ------------------------------------------------------------------

    def _col_eq(self, col: str, val: str) -> str:
        """Return a single-column filter fragment, handling [EMPTY]."""
        if val == "[EMPTY]":
            return f"([{col}] IS NULL OR LTRIM(RTRIM([{col}])) = '')"
        # Escape single quotes to avoid breaking the SQL string
        safe_val = val.replace("'", "''")
        return f"[{col}] = '{safe_val}'"

    def _append(self, filt: str, clause: str, joiner: str = " AND ") -> str:
        if filt:
            return filt + joiner + clause
        return clause

    def _build_filter(self) -> str:  # noqa: C901 (complex by design)
        """
        Build a raw SQL WHERE string from all current UI selections.
        Mirrors VB Filter_BuildFilter() logic exactly.
        """
        f = ""

        # ── Combo fields (General / Meter / AMR) ─────────────────────
        for row_list in (self._general_rows, self._meter_rows, self._amr_rows):
            for db_col, combo, and_or_chk in row_list:
                text = combo.currentText().strip()
                if not text:
                    continue
                joiner = " OR " if and_or_chk.isChecked() else " AND "
                f = self._append(f, self._col_eq(db_col, text), joiner)

        # ── Form / Base special pair ──────────────────────────────────
        form_text = (self._meter_form_combo.currentText().strip()
                     if self._meter_form_combo else "")
        base_text = (self._meter_base_combo.currentText().strip()
                     if self._meter_base_combo else "")
        form_joiner = (
            " OR " if (self._meter_form_check and self._meter_form_check.isChecked())
            else " AND "
        )
        if form_text and base_text:
            pair = f"({self._col_eq('Form', form_text)} AND {self._col_eq('Meter_Base', base_text)})"
            f = self._append(f, pair, form_joiner)
        elif form_text:
            f = self._append(f, self._col_eq("Form", form_text), form_joiner)
        elif base_text:
            f = self._append(f, self._col_eq("Meter_Base", base_text), form_joiner)

        # ── Report category radios ────────────────────────────────────
        if self._rb_anomaly.isChecked():
            f = self._append(f, "Anomaly = 'Checked'")
        elif self._rb_failure.isChecked():
            f = self._append(f, "Anomaly <> 'Checked'")

        # ── New ID range ──────────────────────────────────────────────
        nid_from = self._new_id_from.text().strip()
        nid_to   = self._new_id_to.text().strip()
        if nid_from or nid_to:
            if nid_from and nid_to:
                nid_clause = f"[New ID] >= '{nid_from}' AND [New ID] <= '{nid_to}'"
            elif nid_from:
                nid_clause = f"[New ID] >= '{nid_from}'"
            else:
                nid_clause = f"[New ID] <= '{nid_to}'"
            f = self._append(f, nid_clause)

        # ── Date ranges ───────────────────────────────────────────────
        def _add_date_range(filt, from_w, to_w, and_or_chk, col):
            if not (from_w.is_set() or to_w.is_set()):
                return filt
            joiner = " OR " if and_or_chk.isChecked() else " AND "
            if from_w.is_set() and to_w.is_set():
                clause = (f"([{col}] >= '{from_w.get_value()}'"
                          f" AND [{col}] <= '{to_w.get_value()}')")
            elif from_w.is_set():
                clause = f"[{col}] >= '{from_w.get_value()}'"
            else:
                clause = f"[{col}] <= '{to_w.get_value()}'"
            return self._append(filt, clause, joiner)

        f = _add_date_range(f, self._df_from,  self._df_to,  self._df_and_or,  "Date Failed")
        f = _add_date_range(f, self._dc_from,  self._dc_to,  self._dc_and_or,  "Date Corrected")
        f = _add_date_range(f, self._da_from,  self._da_to,  self._da_and_or,  "Date Approved")
        f = _add_date_range(f, self._dcl_from, self._dcl_to, self._dcl_and_or, "Date Closed")

        # ── Ready For Review section ──────────────────────────────────
        if not self._chk_rfr_disable.isChecked():
            tcc_append = " AND TCC_REVIEW_REQUIRED = 'Checked'" if self._chk_tcc_required.isChecked() else ""

            rfr_clauses = []
            if self._chk_pac2.isChecked() and self._chk_pac2.isEnabled():
                rfr_clauses.append(
                    "(Level LIKE 'PAC 2%' AND TCC_REVIEW_REQUIRED = 'Checked'"
                    " AND FR_READY_FOR_REVIEW = 'Checked' AND FR_APPROVED = 'Unchecked')"
                )
            if self._chk_pac1.isChecked() and self._chk_pac1.isEnabled():
                rfr_clauses.append(
                    f"(Level LIKE 'PAC 1%' AND FR_READY_FOR_REVIEW = 'Checked'"
                    f" AND FR_APPROVED = 'Unchecked'{tcc_append})"
                )
            if self._chk_cit.isChecked() and self._chk_cit.isEnabled():
                rfr_clauses.append(
                    f"(Level LIKE 'CIT%' AND FR_READY_FOR_REVIEW = 'Checked'"
                    f" AND FR_APPROVED = 'Unchecked'{tcc_append})"
                )
            if self._chk_fpa.isChecked() and self._chk_fpa.isEnabled():
                rfr_clauses.append(
                    f"(Level LIKE 'FPA%' AND FR_READY_FOR_REVIEW = 'Checked'"
                    f" AND FR_APPROVED = 'Unchecked'{tcc_append})"
                )
            if self._chk_eng.isChecked() and self._chk_eng.isEnabled():
                rfr_clauses.append(
                    f"(Level LIKE 'ENG%' AND FR_READY_FOR_REVIEW = 'Checked'"
                    f" AND FR_APPROVED = 'Unchecked'{tcc_append})"
                )
            if self._chk_oem.isChecked() and self._chk_oem.isEnabled():
                rfr_clauses.append(
                    f"(Level LIKE 'OEM%' AND FR_READY_FOR_REVIEW = 'Checked'"
                    f" AND FR_APPROVED = 'Unchecked'{tcc_append})"
                )

            for clause in rfr_clauses:
                f = self._append(f, clause, " OR ")

            if self._rb_rfr_all_ready.isChecked() and self._rb_rfr_all_ready.isEnabled():
                f = self._append(
                    f,
                    f"(FR_READY_FOR_REVIEW = 'Checked' AND FR_APPROVED = 'Unchecked'{tcc_append})",
                    " OR ",
                )

            if self._chk_open_only.isChecked() and self._chk_open_only.isEnabled():
                f = self._append(
                    f,
                    f"(FR_READY_FOR_REVIEW = 'Unchecked'{tcc_append})",
                )

            if self._chk_transferred.isChecked() and self._chk_transferred.isEnabled():
                f = self._append(
                    f,
                    f"(Original_Report_Num IS NOT NULL"
                    f" AND LTRIM(RTRIM(Original_Report_Num)) <> ''{tcc_append})",
                )

        return f

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def _on_build_clicked(self):
        new_filter = self._build_filter().strip()
        existing   = self._sql_preview.toPlainText().strip()

        if self._chk_preserve.isChecked() and existing and new_filter:
            joiner = " OR " if self._chk_preserve_and_or.isChecked() else " AND "
            combined = f"({existing}){joiner}({new_filter})"
            self._sql_preview.setPlainText(combined)
        elif self._chk_preserve.isChecked() and existing and not new_filter:
            pass  # do nothing — keep existing filter
        else:
            self._sql_preview.setPlainText(new_filter)

    def _on_apply_clicked(self):
        where = self._sql_preview.toPlainText().strip()
        rows = search_with_filter(where)
        self.result_rows   = rows
        self.result_clause = where
        self.accept()

    def _on_reset_clicked(self):
        # Clear all combo selections
        for row_list in (self._general_rows, self._meter_rows, self._amr_rows):
            for _, combo, chk in row_list:
                combo.setCurrentIndex(0)
                chk.setChecked(False)
        if self._meter_form_combo:
            self._meter_form_combo.setCurrentIndex(0)
        if self._meter_base_combo:
            self._meter_base_combo.setCurrentIndex(0)
        if self._meter_form_check:
            self._meter_form_check.setChecked(False)

        # Clear dates
        for w in (self._df_from, self._df_to, self._dc_from, self._dc_to,
                  self._da_from, self._da_to, self._dcl_from, self._dcl_to):
            w._clear()

        # Reset date AND/OR
        for chk in (self._df_and_or, self._dc_and_or, self._da_and_or, self._dcl_and_or):
            chk.setChecked(False)

        # Reset New ID
        self._new_id_from.clear()
        self._new_id_to.clear()

        # Reset radios
        self._rb_all.setChecked(True)

        # Reset Ready For Review
        self._chk_rfr_disable.setChecked(True)
        for c in (self._chk_pac1, self._chk_pac2, self._chk_cit,
                  self._chk_fpa, self._chk_eng, self._chk_oem,
                  self._chk_tcc_required, self._chk_open_only, self._chk_transferred):
            c.setChecked(False)
        self._rb_rfr_all_ready.setChecked(False)

        # Clear preserve + preview
        self._chk_preserve.setChecked(False)
        self._chk_preserve_and_or.setChecked(False)
        self._sql_preview.clear()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
        else:
            super().keyPressEvent(event)
