"""
Desktop Avatar Module for Personal AI Assistant.
Provides a floating, transparent, draggable interactive AI companion on the Windows desktop.
"""

import math
import sys
from typing import Optional
from PyQt6.QtCore import Qt, QPoint, QTimer, QRectF, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QRadialGradient, QPen, QBrush, QFont, QCursor, QAction
from PyQt6.QtWidgets import QWidget, QMenu, QLabel, QVBoxLayout

from config import config_manager
from core.agent import AgentState


class SpeechBubble(QWidget):
    """Floating speech bubble above the avatar."""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        self.label = QLabel("", self)
        self.label.setWordWrap(True)
        self.label.setStyleSheet("""
            QLabel {
                background-color: rgba(22, 27, 34, 0.95);
                color: #58a6ff;
                border: 1px solid #388bfd;
                border-radius: 10px;
                padding: 10px 14px;
                font-size: 12px;
                font-weight: 500;
                font-family: 'Segoe UI', sans-serif;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.label)
        self.setMaximumWidth(280)
        self.hide()

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

    def show_message(self, text: str, duration_ms: int = 5000):
        if not text:
            return
        # Limit bubble length
        display_text = text if len(text) <= 160 else text[:157] + "..."
        self.label.setText(display_text)
        self.adjustSize()
        self.show()
        self._hide_timer.start(duration_ms)


class DesktopAvatar(QWidget):
    """Interactive floating desktop widget."""

    clicked = pyqtSignal()
    open_dashboard_requested = pyqtSignal()
    trigger_voice_requested = pyqtSignal()
    capture_screen_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        
        # Window attributes
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.SubWindow
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

        # Size & Position
        size = config_manager.get("avatar.size", 150)
        self.setFixedSize(size, size)
        
        saved_x = config_manager.get("avatar.position_x")
        saved_y = config_manager.get("avatar.position_y")
        if saved_x is not None and saved_y is not None:
            self.move(int(saved_x), int(saved_y))
        else:
            # Default to bottom-right corner
            screen = self.screen().geometry()
            self.move(screen.width() - size - 40, screen.height() - size - 100)

        # State and Animation
        self.current_state = AgentState.IDLE
        self.anim_phase = 0.0
        self.pulse_scale = 1.0
        
        # Dragging support
        self._drag_pos = QPoint()
        self._is_dragging = False

        # Speech bubble
        self.bubble = SpeechBubble()

        # Animation timer (60 FPS)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_animation)
        self.timer.start(16)

    def set_state(self, state: AgentState):
        """Updates visual state."""
        self.current_state = state
        self.update()

    def show_speech(self, text: str):
        """Displays text in floating speech bubble above avatar."""
        self.bubble.show_message(text)
        self._update_bubble_position()

    def _update_bubble_position(self):
        bubble_x = self.x() + (self.width() // 2) - (self.bubble.width() // 2)
        bubble_y = self.y() - self.bubble.height() - 10
        self.bubble.move(max(10, bubble_x), max(10, bubble_y))

    def _update_animation(self):
        """Tick function for smooth 60fps animations."""
        self.anim_phase += 0.05
        if self.anim_phase > 2 * math.pi:
            self.anim_phase = 0.0

        if self.current_state == AgentState.IDLE:
            self.pulse_scale = 0.95 + 0.05 * math.sin(self.anim_phase * 1.5)
        elif self.current_state == AgentState.LISTENING:
            self.pulse_scale = 0.90 + 0.12 * math.sin(self.anim_phase * 4.0)
        elif self.current_state == AgentState.THINKING:
            self.pulse_scale = 0.92 + 0.08 * math.cos(self.anim_phase * 5.0)
        elif self.current_state == AgentState.SPEAKING:
            self.pulse_scale = 0.88 + 0.15 * abs(math.sin(self.anim_phase * 6.0))
        elif self.current_state == AgentState.WORKING:
            self.pulse_scale = 0.94 + 0.08 * math.sin(self.anim_phase * 7.0)

        self.update()
        if self.bubble.isVisible():
            self._update_bubble_position()

    def paintEvent(self, event):
        """Draws the dynamic futuristic AI core avatar."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        center_x, center_y = w / 2.0, h / 2.0
        base_radius = (min(w, h) / 2.0) - 15

        # Colors based on state
        if self.current_state == AgentState.IDLE:
            glow_color = QColor(0, 180, 255, 180) # Cyber Blue
            core_color = QColor(10, 35, 70, 240)
            ring_color = QColor(88, 166, 255, 200)
        elif self.current_state == AgentState.LISTENING:
            glow_color = QColor(46, 204, 113, 220) # Emerald Green
            core_color = QColor(15, 60, 30, 240)
            ring_color = QColor(63, 232, 135, 240)
        elif self.current_state == AgentState.THINKING:
            glow_color = QColor(168, 85, 247, 220) # Purple/Violet
            core_color = QColor(45, 20, 70, 240)
            ring_color = QColor(216, 180, 254, 220)
        elif self.current_state == AgentState.SPEAKING:
            glow_color = QColor(236, 72, 153, 220) # Neon Pink / Magenta
            core_color = QColor(65, 15, 40, 240)
            ring_color = QColor(244, 114, 182, 240)
        elif self.current_state == AgentState.WORKING:
            glow_color = QColor(245, 158, 11, 230) # Amber / Gold
            core_color = QColor(60, 35, 10, 240)
            ring_color = QColor(251, 191, 36, 240)
        else: # ERROR
            glow_color = QColor(239, 68, 68, 220)
            core_color = QColor(60, 10, 10, 240)
            ring_color = QColor(248, 113, 113, 240)

        current_radius = base_radius * self.pulse_scale

        # 1. Outer Glow
        glow = QRadialGradient(center_x, center_y, current_radius + 12)
        glow.setColorAt(0.0, glow_color)
        glow.setColorAt(0.7, QColor(glow_color.red(), glow_color.green(), glow_color.blue(), 50))
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setBrush(QBrush(glow))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(center_x - current_radius - 12, center_y - current_radius - 12, (current_radius + 12)*2, (current_radius + 12)*2))

        # 2. Outer Rotating Orbital Ring
        painter.save()
        painter.translate(center_x, center_y)
        rotation_deg = math.degrees(self.anim_phase * (3.0 if self.current_state == AgentState.THINKING else 1.0))
        painter.rotate(rotation_deg)
        
        pen = QPen(ring_color, 2.5, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QRectF(-current_radius - 2, -current_radius - 2, (current_radius + 2)*2, (current_radius + 2)*2))
        painter.restore()

        # 3. Inner Core Sphere
        core_grad = QRadialGradient(center_x - (current_radius * 0.3), center_y - (current_radius * 0.3), current_radius)
        core_grad.setColorAt(0.0, QColor(255, 255, 255, 240))
        core_grad.setColorAt(0.3, glow_color)
        core_grad.setColorAt(0.8, core_color)
        core_grad.setColorAt(1.0, QColor(5, 5, 10, 250))
        
        painter.setBrush(QBrush(core_grad))
        painter.setPen(QPen(ring_color, 1.5))
        painter.drawEllipse(QRectF(center_x - current_radius, center_y - current_radius, current_radius*2, current_radius*2))

        # 4. State Icon / Symbol in Center
        painter.setPen(QColor(255, 255, 255, 220))
        font = QFont("Segoe UI", 10, QFont.Weight.Bold)
        painter.setFont(font)
        
        icon_text = "AI"
        if self.current_state == AgentState.LISTENING:
            icon_text = "MIC"
        elif self.current_state == AgentState.THINKING:
            icon_text = "..."
        elif self.current_state == AgentState.SPEAKING:
            icon_text = ")))"
        elif self.current_state == AgentState.WORKING:
            icon_text = "EXE"

        painter.drawText(QRectF(center_x - 30, center_y - 15, 60, 30), Qt.AlignmentFlag.AlignCenter, icon_text)

    # Mouse & Drag Events
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = True
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        elif event.button() == Qt.MouseButton.RightButton:
            self._show_context_menu(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event):
        if self._is_dragging and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            self._update_bubble_position()
            event.accept()

    def mouseReleaseEvent(self, event):
        if self._is_dragging:
            self._is_dragging = False
            # Save position
            config_manager.set("avatar.position_x", self.x(), auto_save=False)
            config_manager.set("avatar.position_y", self.y(), auto_save=True)
            event.accept()

    def mouseDoubleClickEvent(self, event):
        """Double click opens the master dashboard."""
        self.open_dashboard_requested.emit()

    def _show_context_menu(self, global_pos: QPoint):
        """Displays right-click menu."""
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #161b22;
                color: #c9d1d9;
                border: 1px solid #30363d;
                border-radius: 8px;
                padding: 6px;
                font-family: 'Segoe UI', sans-serif;
            }
            QMenu::item {
                padding: 8px 24px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #1f6feb;
                color: #ffffff;
            }
        """)

        act_dash = QAction("⚙️ Панель настроек", self)
        act_dash.triggered.connect(self.open_dashboard_requested.emit)
        menu.addAction(act_dash)

        act_see = QAction("👁️ Сделать скриншот и спросить", self)
        act_see.triggered.connect(self.capture_screen_requested.emit)
        menu.addAction(act_see)

        menu.addSeparator()

        act_quit = QAction("❌ Закрыть ассистента", self)
        act_quit.triggered.connect(sys.exit)
        menu.addAction(act_quit)

        menu.exec(global_pos)
