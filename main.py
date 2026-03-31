"""
Application entry point.

Run from the project root:
    python main.py
"""

import sys
from pathlib import Path
from PyQt6.QtWidgets import QApplication, QMessageBox
from ui.dashboard import DashboardWindow
from ui.detail_view import open_detail
from ui.new_report import open_new_report
from ui.login import run_login
from auth.session import current_user


def _load_stylesheet(app: QApplication) -> None:
    """Load assets/style.qss relative to this file, silently skip if missing."""
    qss_path = Path(__file__).resolve().parent / "assets" / "style.qss"
    if qss_path.exists():
        app.setStyleSheet(qss_path.read_text(encoding="utf-8"))
    else:
        print(f"[warn] Stylesheet not found at {qss_path} — running unstyled.")


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    _load_stylesheet(app)

    # Show login dialog before anything else — mirrors frmLogin splash on startup
    if not run_login():
        sys.exit(0)

    win = DashboardWindow()

    win.report_selected.connect(
        lambda idx: open_detail(idx, parent=win, on_deleted=win._load_all)
    )

    def _on_new_report():
        if not current_user.can_create:
            QMessageBox.warning(
                win,
                "Access Denied",
                "Your account does not have permission to create new reports.",
            )
            return
        dlg = open_new_report(parent=win)
        if dlg.result() == dlg.DialogCode.Accepted:
            win._load_all()

    win.new_report_requested.connect(_on_new_report)

    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()