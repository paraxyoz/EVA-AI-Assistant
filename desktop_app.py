"""
EVA AI — Native Dual-Window Desktop Application (PyQt6 + QtWebEngine).
Architecture:
1. AvatarDesktopWindow: Frameless, 100% transparent background 3D VRM companion living directly on the Windows desktop.
   Can be dragged anywhere on screen, resized, and rotated 360 degrees without restrictions.
2. ControlCenterWindow: Separate dark monochrome desktop window for Settings, Installed Ollama Models dropdown,
   Real 3D Clothing Layer toggles (+ NSFW), and Prompt History. Can be hidden to background leaving only the 3D model.
"""

import os
import sys
import ctypes
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QUrl, QPoint, QSize, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QFontDatabase, QFont, QIcon, QPixmap, QPainter, QColor, QPen, QAction
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QSystemTrayIcon, QMenu, QSizeGrip
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings, QWebEnginePage, QWebEngineProfile

from core.events import agent_signals


def hide_console_window():
    """Hides any attached Windows console window so only the native GUI is visible."""
    if os.name == "nt":
        try:
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 0)
        except Exception:
            pass


def create_monochrome_app_icon() -> QIcon:
    """Renders a clean geometric monochrome icon for the native windows and system tray."""
    pix = QPixmap(64, 64)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    painter.setBrush(QColor(16, 16, 20))
    painter.setPen(QPen(QColor(244, 244, 245), 3))
    painter.drawRoundedRect(6, 6, 52, 52, 14, 14)

    painter.setPen(QPen(QColor(244, 244, 245), 3.5))
    painter.drawLine(20, 22, 44, 22)
    painter.drawLine(20, 32, 38, 32)
    painter.drawLine(20, 42, 44, 42)
    painter.drawLine(20, 22, 20, 42)

    painter.end()
    return QIcon(pix)


class AutoGrantWebEnginePage(QWebEnginePage):
    """Automatically grants microphone audio capture permission for voice commands."""

    def __init__(self, profile: QWebEngineProfile, parent=None):
        super().__init__(profile, parent)
        self.featurePermissionRequested.connect(self._on_feature_permission)

    def _on_feature_permission(self, security_origin: QUrl, feature: QWebEnginePage.Feature):
        if feature in (
            QWebEnginePage.Feature.MediaAudioCapture,
            QWebEnginePage.Feature.MediaVideoCapture,
            QWebEnginePage.Feature.MediaAudioVideoCapture,
        ):
            self.setFeaturePermission(
                security_origin,
                feature,
                QWebEnginePage.PermissionPolicy.PermissionGrantedByUser
            )


class AvatarDragHeader(QWidget):
    """Subtle floating drag bar at the top of the 3D Avatar window to move her anywhere on the desktop."""

    def __init__(self, parent_window: QMainWindow, on_open_control):
        super().__init__(parent_window)
        self.parent_window = parent_window
        self._drag_pos: Optional[QPoint] = None
        self.setFixedHeight(28)
        self.setCursor(Qt.CursorShape.SizeAllCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(6)

        self.pill = QWidget(self)
        self.pill.setStyleSheet("""
            QWidget {
                background-color: rgba(14, 14, 18, 175);
                border: 1px solid rgba(255, 255, 255, 28);
                border-radius: 7px;
            }
        """)
        pill_layout = QHBoxLayout(self.pill)
        pill_layout.setContentsMargins(10, 2, 6, 2)
        pill_layout.setSpacing(8)

        lbl = QLabel("EVA 3D  •  ПЕРЕТАЩИТЬ", self.pill)
        lbl.setStyleSheet("color: #a1a1aa; font-size: 10px; border: none; background: transparent; letter-spacing: 1px;")
        pill_layout.addWidget(lbl)

        btn_cfg = QPushButton("НАСТРОЙКИ", self.pill)
        btn_cfg.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cfg.setStyleSheet("""
            QPushButton {
                background-color: #1c1c22;
                color: #f4f4f5;
                border: 1px solid rgba(255, 255, 255, 35);
                border-radius: 4px;
                padding: 2px 7px;
                font-size: 9px;
            }
            QPushButton:hover {
                background-color: #f4f4f5;
                color: #09090b;
            }
        """)
        btn_cfg.clicked.connect(on_open_control)
        pill_layout.addWidget(btn_cfg)

        layout.addStretch()
        layout.addWidget(self.pill)
        layout.addStretch()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.parent_window.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.parent_window.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None


class AvatarDesktopWindow(QMainWindow):
    """
    Window 1: Transparent Desktop 3D Avatar Companion.
    Contains ONLY the 3D model with zero background so she lives directly on the Windows desktop.
    """

    def __init__(self, port: int, on_toggle_control):
        super().__init__()
        self.port = port
        self.on_toggle_control = on_toggle_control

        self.setWindowTitle("EVA AI — 3D Аватар")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.resize(480, 740)

        # Position on the right side of the primary desktop by default
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move(geo.right() - 500, geo.bottom() - 750)

        central = QWidget(self)
        central.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        central.setStyleSheet("background: transparent;")
        self.setCentralWidget(central)

        vbox = QVBoxLayout(central)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        # Top drag handle for moving the 3D model anywhere on the desktop (visible on hover)
        self.drag_header = AvatarDragHeader(self, on_open_control=self.on_toggle_control)
        self.drag_header.pill.hide()
        vbox.addWidget(self.drag_header)

        # Transparent WebGL 3D View
        self.web_view = QWebEngineView(central)
        self.web_view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.web_view.setStyleSheet("background: transparent;")

        profile = QWebEngineProfile.defaultProfile()
        profile.clearHttpCache()
        page = AutoGrantWebEnginePage(profile, self.web_view)
        page.setBackgroundColor(Qt.GlobalColor.transparent)
        self.web_view.setPage(page)

        settings = self.web_view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)

        self.web_view.renderProcessTerminated.connect(
            lambda _status, _code: QTimer.singleShot(150, self.web_view.reload)
        )
        self.web_view.load(QUrl(f"http://127.0.0.1:{self.port}/avatar"))
        vbox.addWidget(self.web_view, 1)

        # Subtle bottom-right resize grip
        grip_row = QHBoxLayout()
        grip_row.setContentsMargins(0, 0, 4, 4)
        grip_row.addStretch()
        grip = QSizeGrip(central)
        grip.setStyleSheet("background: transparent; width: 14px; height: 14px;")
        grip_row.addWidget(grip)
        vbox.addLayout(grip_row)

    def enterEvent(self, event):
        self.drag_header.pill.show()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.drag_header.pill.hide()
        super().leaveEvent(event)


class CustomTitleBar(QWidget):
    """Frameless dark monochrome titlebar for Window 2 (Control Center & Prompt History)."""

    def __init__(self, parent_window: QMainWindow, on_hide_to_bg, on_quit_app):
        super().__init__(parent_window)
        self.parent_window = parent_window
        self._drag_pos: Optional[QPoint] = None
        self.setFixedHeight(38)
        self.setStyleSheet("""
            QWidget {
                background-color: #09090b;
                border-bottom: 1px solid #1f1f26;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 10, 0)
        layout.setSpacing(8)

        title = QLabel("EVA AI  —  НАСТРОЙКИ И ИСТОРИЯ ПРОМПТОВ", self)
        title.setStyleSheet("color: #a1a1aa; font-size: 11px; letter-spacing: 1.2px; border: none;")
        layout.addWidget(title)
        layout.addStretch()

        btn_style = """
            QPushButton {
                background-color: #141419;
                color: #d4d4d8;
                border: 1px solid #27272f;
                border-radius: 5px;
                padding: 4px 10px;
                font-size: 10px;
            }
            QPushButton:hover {
                background-color: #27272f;
                color: #ffffff;
            }
        """

        btn_hide = QPushButton("СКРЫТЬ В ФОН", self)
        btn_hide.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_hide.setStyleSheet(btn_style)
        btn_hide.clicked.connect(on_hide_to_bg)
        layout.addWidget(btn_hide)

        btn_quit = QPushButton("ВЫХОД", self)
        btn_quit.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_quit.setStyleSheet("""
            QPushButton {
                background-color: #18181f;
                color: #a1a1aa;
                border: 1px solid #27272f;
                border-radius: 5px;
                padding: 4px 10px;
                font-size: 10px;
            }
            QPushButton:hover {
                background-color: #f4f4f5;
                color: #09090b;
            }
        """)
        btn_quit.clicked.connect(on_quit_app)
        layout.addWidget(btn_quit)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.parent_window.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.parent_window.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None


class ControlCenterWindow(QMainWindow):
    """
    Window 2: Native Desktop Control Center (Settings + Installed Ollama Models + Custom Commands + Prompt History).
    Runs in the background when hidden so the user can interact solely with the 3D Avatar on the desktop.
    """

    def __init__(self, port: int, on_quit_app):
        super().__init__()
        self.port = port
        self.on_quit_app = on_quit_app

        self.setWindowTitle("EVA AI — Управление и История")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setMinimumSize(980, 660)
        self.resize(1220, 800)
        self.setStyleSheet("background-color: #09090b;")

        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move(max(30, geo.left() + 50), max(30, (geo.height() - 800) // 2))

        central = QWidget(self)
        self.setCentralWidget(central)

        vbox = QVBoxLayout(central)
        vbox.setContentsMargins(1, 1, 1, 1)
        vbox.setSpacing(0)

        self.title_bar = CustomTitleBar(self, on_hide_to_bg=self.hide, on_quit_app=self.on_quit_app)
        vbox.addWidget(self.title_bar)

        self.web_view = QWebEngineView(central)
        profile = QWebEngineProfile.defaultProfile()
        profile.clearHttpCache()
        page = AutoGrantWebEnginePage(profile, self.web_view)
        page.setBackgroundColor(QColor("#09090b"))
        self.web_view.setPage(page)

        settings = self.web_view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)

        self.web_view.renderProcessTerminated.connect(
            lambda _status, _code: QTimer.singleShot(150, self.web_view.reload)
        )
        import time as _t
        self.web_view.load(QUrl(f"http://127.0.0.1:{self.port}/control?v={int(_t.time())}"))
        vbox.addWidget(self.web_view, 1)

    def closeEvent(self, event):
        """Closing Window 2 hides it to the background so the 3D Avatar stays alive on the desktop."""
        event.ignore()
        self.hide()


class WindowBridge(QObject):
    """Thread-safe Qt signal bridge for handling window actions sent from WebSocket IPC."""
    action_received = pyqtSignal(str)


class EVADesktopSuite:
    """Manages both native windows (AvatarDesktopWindow & ControlCenterWindow) and System Tray."""

    def __init__(self, port: int = 7865):
        hide_console_window()

        os.environ.setdefault(
            "QTWEBENGINE_CHROMIUM_FLAGS",
            "--enable-gpu-rasterization --enable-zero-copy --ignore-gpu-blocklist --autoplay-policy=no-user-gesture-required"
        )

        self.port = port
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
        self.app.setApplicationName("EVA AI")

        font_path = Path(__file__).parent.resolve() / "web" / "fonts" / "Tovar.otf"
        if font_path.exists():
            font_id = QFontDatabase.addApplicationFont(str(font_path))
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families:
                self.app.setFont(QFont(families[0], 10))

        self.icon = create_monochrome_app_icon()
        self.app.setWindowIcon(self.icon)

        self.avatar_win = AvatarDesktopWindow(port=self.port, on_toggle_control=self.toggle_control_window)
        self.control_win = ControlCenterWindow(port=self.port, on_quit_app=self.quit_application)

        self.bridge = WindowBridge()
        self.bridge.action_received.connect(self._handle_window_action)
        agent_signals.on("window_action", lambda act: self.bridge.action_received.emit(act))

        self._init_tray()

    def _init_tray(self):
        self.tray = QSystemTrayIcon(self.icon, self.app)
        self.tray.setToolTip("EVA AI — 3D Desktop Companion")

        menu = QMenu()
        menu.setStyleSheet("""
            QMenu {
                background-color: #101014;
                color: #f4f4f5;
                border: 1px solid #27272f;
                padding: 6px;
            }
            QMenu::item {
                padding: 7px 18px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #f4f4f5;
                color: #09090b;
            }
        """)

        act_control = QAction("Открыть Настройки и Историю", menu)
        act_control.triggered.connect(self.show_control_window)
        menu.addAction(act_control)

        act_hide_control = QAction("Скрыть настройки в фон", menu)
        act_hide_control.triggered.connect(self.control_win.hide)
        menu.addAction(act_hide_control)

        act_avatar = QAction("Показать / скрыть 3D-модель", menu)
        act_avatar.triggered.connect(self.toggle_avatar_window)
        menu.addAction(act_avatar)

        menu.addSeparator()

        act_quit = QAction("Полный выход из EVA AI", menu)
        act_quit.triggered.connect(self.quit_application)
        menu.addAction(act_quit)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_control_window()

    def _handle_window_action(self, action: str):
        if action == "toggle_control":
            self.toggle_control_window()
        elif action == "hide_control":
            self.control_win.hide()
        elif action == "show_control":
            self.show_control_window()
        elif action == "show_avatar":
            self.show_avatar_window()
        elif action == "hide_avatar":
            self.avatar_win.hide()
        elif action == "toggle_avatar":
            self.toggle_avatar_window()
        elif action == "quit_app":
            self.quit_application()

    def toggle_control_window(self):
        if self.control_win.isVisible():
            self.control_win.hide()
        else:
            self.show_control_window()

    def toggle_avatar_window(self):
        if self.avatar_win.isVisible():
            self.avatar_win.hide()
        else:
            self.show_avatar_window()

    def show_control_window(self):
        self.control_win.showNormal()
        self.control_win.raise_()
        self.control_win.activateWindow()

    def show_avatar_window(self):
        self.avatar_win.showNormal()
        self.avatar_win.raise_()

    def quit_application(self):
        self.tray.hide()
        self.avatar_win.close()
        self.control_win.close()
        self.app.quit()
        os._exit(0)

    def run(self):
        from config import config_manager
        if config_manager.get("avatar.show_on_desktop", True):
            self.avatar_win.show()
        self.control_win.show()
        sys.exit(self.app.exec())
