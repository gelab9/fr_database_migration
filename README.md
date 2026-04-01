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
