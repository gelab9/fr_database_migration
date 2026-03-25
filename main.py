"""
Application entry point.

Run from the project root:
    python main.py
"""

import sys
from PyQt6.QtWidgets import QApplication
from ui.dashboard import DashboardWindow


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = DashboardWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
