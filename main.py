"""
Application entry point.

Run from the project root:
    python main.py
"""

import sys
from PyQt6.QtWidgets import QApplication
from ui.dashboard import DashboardWindow
from ui.detail_view import open_detail
from ui.new_report import open_new_report


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = DashboardWindow()

    # open_detail wires save_requested → update_report internally
    win.report_selected.connect(lambda idx: open_detail(idx, parent=win))

    # After new report dialog closes, refresh the table so the new row appears
    def _on_new_report():
        dlg = open_new_report(parent=win)
        if dlg.result() == dlg.DialogCode.Accepted:
            win._load_all()

    win.new_report_requested.connect(_on_new_report)

    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
