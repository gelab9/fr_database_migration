# FR Database Migration

## Project Overview
A desktop application rebuild of a legacy Visual Basic failure report management system.
Engineers use this to log, track, and manage failure reports for products tested in the lab.
Reports follow a formal review and approval workflow involving engineers, TCC reviewers, and approvers.

## Tech Stack
- **Language:** Python
- **UI Framework:** PyQt6 (cross-platform — Windows and Raspberry Pi)
- **Database:** Microsoft SQL Server (restored from legacy .bak file)
- **DB Driver:** pyodbc + sqlalchemy
- **Version Control:** GitHub
- **IDE:** VS Code

## Project Structure
```
fr_database_migration/
├── config/
│   └── settings.py         # DB connection string (not committed to Git)
├── db/
│   ├── connection.py       # pyodbc connection handler
│   └── queries.py          # reusable query functions
├── migration/
│   ├── schema.py           # schema reading/recreation scripts
│   └── data.py             # data transformation scripts
├── reports/                # generated report outputs
├── tests/
│   └── test_connection.py  # DB connection and inventory test
├── .gitignore
├── pyenv.cfg
└── README.md
```

## Database Summary
- **Primary table:** `Failure Report` —  containing a continuous about of records
- **Secondary table:** `ATTACHMENT` — stores file attachments (currently empty)
- **Custom stored procedures:** `GET_FR_DATA` (SELECT * ORDER BY New ID), `REPLACE_ATTACHMENT_PATH`

## Key Field Groups in Failure Report Table
- **IDs:** Index, New ID, Original ID, Original_Project_Num, Original_Report_Num
- **Meter info:** EUT_TYPE, Meter_Manufacturer, Meter, Meter_Type, Meter_SubType, Meter_SubTypeII, Meter_DSP_Rev, Meter_PCBA, Meter_PCBA_Rev, Meter_Software, Meter_Software_Rev, Meter_Voltage, Form, Meter_Base, Meter_Serial_Number, Meter_Notes
- **AMR info:** AMR, AMR Rev, AMR_Manufacturer, AMR_SN, AMR_Type, AMR_SUBType, AMR_SUBTypeII, AMR_SUBTypeIII, AMR_Notes, AMR_PCBA, AMR_PCBA_Rev, AMR_Software, AMR_Software_Rev, AMR_IP_LAN_ID, AMR_Voltage
- **Test info:** Project, Project_Number, FW Ver, Test_Matrix_ID, Test, Test_Type, Level, Date Failed, Tested By
- **Failure content:** Failure Description, Corrective Action, Engineering Notes, TCC Comments, Test_Equipment_ID
- **Workflow:** Assigned To, Corrected By, Date Corrected, Approved By, Date Approved, Date Closed, Pass, Anomaly, Failed_Sample_Ready, Failed_Sample_Ready_Date
- **Review/approval flags:** TCC_Review_Required, FR_Ready_For_Review, FR_Approved
- **TCC reviewers:** TCC 1, TCC 2, TCC 3, TCC 4, TCC 5, TCC 6
- **Attachments:** Attachments (field in main table)

## Dropdown Field Values
**EUT_TYPE:** AMI, Meter Only, AMR Only, OTHER EUT

**Test_Type:** EMC, Reliability, Functional, Environmental, Accuracy, Mechanical, Safety, All, Custom, Past Tests

**Meter_Type:** Revelo, S4X Gen 2, FOCUS AXe, MAXsys, FOCUS AX, S4X, S4X Gen 3, FOCUS Axei, FOCUS Axi, FOCUS AX POLY, FOCUS AL, S4e, Residential, FOCUS, AXEi, Load Control Switch, FOCUS AX EPS, Focus Axe 8W, DEV 2635, PCB Board, Prototype, NextGenMeter, AXe, FOCUS AXe Gen 2, FOCUS RXRe, E360, S4x RXR, NA
> Note: Meter_Type list needs cleanup — NA/N/A/- are duplicates, NextGenMeter/NextGen/NexGen/NGM likely same product. Confirm with engineers before finalizing.

# Next on the Agenda
**Code Cleaning:**

*Ignore, this is a personal question* Frank question: What is the difference between Matrix ID and Project Name/ID

*Ignore for now* Get rid of Matrix ID, not used (check to make sure we don't need)

*Ignore this is a personal task for now* Get a list of every single test in the lab - different ones for HQ, ANSI, and Landis + Gyr

*Attachements is not fixed*

Option in the 'attachments' area where 'open checked' in the original to needs to actually open up attachments from the application, I am not able to, let's fix this
Checked and it is leading to the wrong folder where it is actually stored, it needs to line up with new HQA drive: HQA (\\uslafvs001038)(Z:)\TEST DATA\00-GE LAB IN PROCESS and find the attachments within that drive, not sure where it is leading to. The button also needs an outline for the 'Open Folder' button.

Example of code used in another project to use a browse:
# Python
      browse_btn = QPushButton("Browse…")
            browse_btn.setFixedWidth(72)
            browse_btn.setFixedHeight(24)
            browse_btn.setToolTip(
                  "Open a file browser to locate the .xlsm workbook.\n"
                  "Opens to: Z:\\TEST DATA\\00-GE LAB IN PROCESS"
        )
        browse_btn.clicked.connect(self._browse_workbook)
        row.addWidget(browse_btn)
        box.layout().addLayout(row)

        self._working_dir_lbl = QLabel("Working directory: —")
        self._working_dir_lbl.setStyleSheet("color: #555; font-size: 11px;")
        box.layout().addWidget(self._working_dir_lbl)
        return box

    def _browse_workbook(self) -> None:
        # Default to last used dir, then the network share, then home
        last_dir = self._settings.value("last_dir", "")
        if not last_dir or not Path(last_dir).exists():
            last_dir = _DEFAULT_DIR if Path(_DEFAULT_DIR).exists() else ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Test Workbook", last_dir,
            "Excel Workbooks (*.xlsm *.xlsx);;All Files (*)"
        )
        if path:
            self._wb_field.setText(path)
            self._on_workbook_selected(path)


*End of Attachments section*

*FIGURE OUT INFORMATION ABOUT FR WITH FRANK, more information to be continued...*