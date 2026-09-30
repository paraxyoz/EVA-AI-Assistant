"""
Modern Dark Theme and Stylesheets for PyQt6 GUI.
"""

DARK_THEME_QSS = """
QMainWindow, QDialog, QWidget#MainContainer {
    background-color: #0d1117;
    color: #e6edf3;
    font-family: 'Segoe UI', 'Roboto', sans-serif;
    font-size: 13px;
}

QTabWidget::pane {
    border: 1px solid #30363d;
    background: #161b22;
    border-radius: 8px;
    top: -1px;
}

QTabBar::tab {
    background: #0d1117;
    color: #8b949e;
    padding: 10px 18px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    border: 1px solid transparent;
    font-weight: 600;
    font-size: 13px;
}

QTabBar::tab:selected {
    background: #161b22;
    color: #58a6ff;
    border: 1px solid #30363d;
    border-bottom: 1px solid #161b22;
}

QTabBar::tab:hover:!selected {
    color: #c9d1d9;
    background: #161b2280;
}

QGroupBox {
    border: 1px solid #30363d;
    border-radius: 8px;
    margin-top: 18px;
    padding-top: 14px;
    font-weight: bold;
    color: #58a6ff;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 2px 8px;
    background: #161b22;
    border-radius: 4px;
}

QLabel {
    color: #c9d1d9;
}

QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background-color: #0d1117;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 8px 12px;
    color: #f0f6fc;
    selection-background-color: #1f6feb;
}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus {
    border: 1px solid #58a6ff;
    background-color: #0d1117;
}

QComboBox::drop-down {
    border: none;
    padding-right: 8px;
}

QPushButton {
    background-color: #21262d;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 9px 18px;
    color: #c9d1d9;
    font-weight: 600;
}

QPushButton:hover {
    background-color: #30363d;
    border-color: #8b949e;
    color: #ffffff;
}

QPushButton:pressed {
    background-color: #161b22;
}

QPushButton#PrimaryButton {
    background-color: #238636;
    border: 1px solid #2ea043;
    color: #ffffff;
}

QPushButton#PrimaryButton:hover {
    background-color: #2ea043;
}

QPushButton#DangerButton {
    background-color: #da3633;
    border: 1px solid #f85149;
    color: #ffffff;
}

QPushButton#DangerButton:hover {
    background-color: #f85149;
}

QTableWidget {
    background-color: #0d1117;
    border: 1px solid #30363d;
    border-radius: 6px;
    gridline-color: #21262d;
    color: #e6edf3;
}

QHeaderView::section {
    background-color: #161b22;
    color: #8b949e;
    padding: 6px;
    border: 1px solid #21262d;
    font-weight: bold;
}

QScrollBar:vertical {
    border: none;
    background: #0d1117;
    width: 8px;
    margin: 0px;
}

QScrollBar::handle:vertical {
    background: #30363d;
    min-height: 20px;
    border-radius: 4px;
}

QScrollBar::handle:vertical:hover {
    background: #8b949e;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QSlider::groove:horizontal {
    border: 1px solid #30363d;
    height: 6px;
    background: #0d1117;
    border-radius: 3px;
}

QSlider::sub-page:horizontal {
    background: #1f6feb;
    border-radius: 3px;
}

QSlider::handle:horizontal {
    background: #58a6ff;
    border: 1px solid #58a6ff;
    width: 16px;
    margin-top: -5px;
    margin-bottom: -5px;
    border-radius: 8px;
}

QCheckBox {
    color: #c9d1d9;
    spacing: 8px;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border: 1px solid #30363d;
    border-radius: 4px;
    background: #0d1117;
}

QCheckBox::indicator:checked {
    background: #1f6feb;
    border-color: #58a6ff;
}
"""
