from __future__ import annotations

import ctypes
import ctypes.wintypes
import json
import logging
import os
import sys
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, Qt, Signal, QObject
from PySide6.QtGui import QColor, QGuiApplication, QKeyEvent, QMouseEvent, QPainter, QPen, QWheelEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSlider,
    QSpinBox,
    QStyle,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)


APP_NAME = "Grid Overlay"
ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("APPDATA", Path.home())) / "GridOverlay"
DATA_DIR.mkdir(parents=True, exist_ok=True)
SETTINGS_PATH = DATA_DIR / "settings.json"
LOG_PATH = DATA_DIR / "grid-overlay.log"

HOTKEY_NEW = 1
HOTKEY_EDIT = 2
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
VK_F8 = 0x77
VK_E = 0x45
def wheel_modifier_states(event: QWheelEvent) -> tuple[bool, bool, bool]:
    """휠 시점의 Ctrl/Shift 상태를 Qt 창 내부에서 조회합니다."""
    modifiers = event.modifiers() | QGuiApplication.keyboardModifiers()
    ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
    shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
    return ctrl, shift, False


@dataclass
class Settings:
    spacing_x: float = 20.0
    spacing_y: float = 20.0
    offset_x: float = 0.0
    offset_y: float = 0.0
    line_color: str = "#ff4040"
    line_opacity: int = 155
    line_width: float = 1.0
    major_enabled: bool = True
    major_every: int = 5
    major_opacity: int = 235
    major_width: float = 2.0
    outside_opacity: int = 51  # 약 20%
    min_spacing: float = 4.0
    max_spacing: float = 200.0

    @classmethod
    def load(cls) -> "Settings":
        try:
            raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            known = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
            return cls(**known)
        except FileNotFoundError:
            return cls()
        except Exception:
            logging.exception("설정 파일을 읽지 못해 기본값을 사용합니다.")
            return cls()

    def save(self) -> None:
        SETTINGS_PATH.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8"
        )


class HotkeySignals(QObject):
    new_selection = Signal()
    toggle_edit = Signal()
    registration_failed = Signal(str)


class WindowsHotkeyThread(threading.Thread):
    def __init__(self, signals: HotkeySignals) -> None:
        super().__init__(daemon=True)
        self.signals = signals
        self.thread_id: int | None = None

    def run(self) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self.thread_id = kernel32.GetCurrentThreadId()
        registered_f8 = bool(user32.RegisterHotKey(None, HOTKEY_NEW, 0, VK_F8))
        registered_edit = bool(
            user32.RegisterHotKey(None, HOTKEY_EDIT, MOD_CONTROL | MOD_SHIFT, VK_E)
        )
        if not registered_f8:
            self.signals.registration_failed.emit("F8 단축키를 등록하지 못했습니다.")
        if not registered_edit:
            self.signals.registration_failed.emit(
                "Ctrl+Shift+E 단축키를 등록하지 못했습니다."
            )

        msg = ctypes.wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                if msg.wParam == HOTKEY_NEW:
                    self.signals.new_selection.emit()
                elif msg.wParam == HOTKEY_EDIT:
                    self.signals.toggle_edit.emit()

        if registered_f8:
            user32.UnregisterHotKey(None, HOTKEY_NEW)
        if registered_edit:
            user32.UnregisterHotKey(None, HOTKEY_EDIT)

    def stop(self) -> None:
        if self.thread_id:
            ctypes.windll.user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)


def virtual_geometry() -> QRect:
    screens = QGuiApplication.screens()
    if not screens:
        return QRect(0, 0, 800, 600)
    result = QRect(screens[0].geometry())
    for screen in screens[1:]:
        result = result.united(screen.geometry())
    return result


class RegionSelector(QWidget):
    selected = Signal(QRect)
    cancelled = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.origin: QPoint | None = None
        self.current: QPoint | None = None
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setGeometry(virtual_geometry())

    def selection_rect(self) -> QRect:
        if self.origin is None or self.current is None:
            return QRect()
        return QRect(self.origin, self.current).normalized()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 105))
        rect = self.selection_rect()
        if rect.isValid() and not rect.isEmpty():
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(rect, Qt.GlobalColor.transparent)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            painter.setPen(QPen(QColor("#4da3ff"), 2))
            painter.drawRect(rect)
            label = f"{rect.width()} × {rect.height()} px"
            box = QRect(rect.left(), max(0, rect.top() - 28), 150, 24)
            painter.fillRect(box, QColor(20, 20, 20, 210))
            painter.setPen(Qt.GlobalColor.white)
            painter.drawText(box.adjusted(7, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, label)
        else:
            painter.setPen(Qt.GlobalColor.white)
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "그리드를 표시할 그래프 영역을 드래그하세요  ·  Esc 취소",
            )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.origin = event.position().toPoint()
            self.current = self.origin
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self.origin is not None:
            self.current = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self.origin is None:
            return
        self.current = event.position().toPoint()
        rect = self.selection_rect()
        if rect.width() > 0 and rect.height() > 0:
            global_rect = QRect(rect)
            global_rect.translate(self.geometry().topLeft())
            self.selected.emit(global_rect)
        else:
            self.origin = None
            self.current = None
            self.update()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
        else:
            super().keyPressEvent(event)


class ShadeOverlay(QWidget):
    def __init__(self, clear_rect: QRect, opacity: int) -> None:
        super().__init__()
        self.clear_rect = clear_rect
        self.opacity = opacity
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setGeometry(virtual_geometry())

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, self.opacity))
        local_clear = QRect(self.clear_rect)
        local_clear.translate(-self.geometry().topLeft())
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        painter.fillRect(local_clear, Qt.GlobalColor.transparent)


class GridOverlay(QWidget):
    locked_changed = Signal(bool)
    close_requested = Signal()
    new_selection_requested = Signal()

    def __init__(self, rect: QRect, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self.locked = False
        self.status_text = "편집 중 · 휠 간격 · 방향키 위치 · Enter 잠금"
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setGeometry(rect)
        self.panel = SettingsPanel(self)
        self.panel.sync_from_settings()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        # 완전 투명 픽셀은 Windows가 마우스 입력 대상에서 제외할 수 있으므로,
        # 육안으로 구분되지 않는 alpha=1 배경으로 전체 선택 영역을 활성화합니다.
        p.fillRect(self.rect(), QColor(0, 0, 0, 1))
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        color = QColor(self.settings.line_color)
        color.setAlpha(self.settings.line_opacity)
        p.setPen(QPen(color, self.settings.line_width))

        x = self.settings.offset_x % self.settings.spacing_x
        index = 0
        while x <= self.width():
            self._set_grid_pen(p, index)
            p.drawLine(round(x), 0, round(x), self.height())
            x += self.settings.spacing_x
            index += 1
        y = self.settings.offset_y % self.settings.spacing_y
        index = 0
        while y <= self.height():
            self._set_grid_pen(p, index)
            p.drawLine(0, round(y), self.width(), round(y))
            y += self.settings.spacing_y
            index += 1

        if not self.locked:
            p.setPen(QPen(QColor("#4da3ff"), 1, Qt.PenStyle.DashLine))
            p.drawRect(self.rect().adjusted(0, 0, -1, -1))

    def _set_grid_pen(self, painter: QPainter, index: int) -> None:
        major = (
            self.settings.major_enabled
            and self.settings.major_every > 0
            and index % self.settings.major_every == 0
        )
        color = QColor(self.settings.line_color)
        color.setAlpha(
            self.settings.major_opacity if major else self.settings.line_opacity
        )
        width = self.settings.major_width if major else self.settings.line_width
        painter.setPen(QPen(color, width))

    def show_editing(self) -> None:
        self.locked = False
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, False)
        self.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, False)
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
        self.position_panel_outside()
        self.panel.show()
        self.panel.raise_()
        self.locked_changed.emit(False)
        self.update()

    def set_locked(self, locked: bool) -> None:
        self.locked = locked
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, locked)
        self.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, locked)
        self.show()
        self.raise_()
        self.panel.setVisible(not locked)
        if not locked:
            self.activateWindow()
            self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
        self.locked_changed.emit(locked)
        self.update()

    def position_panel_outside(self) -> None:
        self.panel.adjustSize()
        grid_rect = self.geometry()
        screen = QGuiApplication.screenAt(grid_rect.center())
        available = screen.availableGeometry() if screen else virtual_geometry()
        pw, ph = self.panel.width(), self.panel.height()
        gap = 12
        candidates = [
            QPoint(grid_rect.right() + gap, grid_rect.top()),
            QPoint(grid_rect.left() - pw - gap, grid_rect.top()),
            QPoint(grid_rect.left(), grid_rect.bottom() + gap),
            QPoint(grid_rect.left(), grid_rect.top() - ph - gap),
        ]
        for point in candidates:
            panel_rect = QRect(point, self.panel.size())
            if available.contains(panel_rect):
                self.panel.move(point)
                return
        # 화면 여백이 부족한 극단적인 경우에도 우측 상단에 배치합니다.
        self.panel.move(available.right() - pw, available.top() + gap)

    def enterEvent(self, event) -> None:
        if not self.locked:
            self.activateWindow()
            self.setFocus(Qt.FocusReason.MouseFocusReason)
        super().enterEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        raw_delta = event.angleDelta().y()
        if not raw_delta:
            return
        ctrl, shift, alt = wheel_modifier_states(event)
        self.adjust_spacing(
            raw_delta,
            ctrl,
            shift,
            alt,
        )
        event.accept()

    def adjust_spacing(self, raw_delta: int, ctrl: bool, shift: bool, alt: bool) -> None:
        steps = 1.0 if raw_delta > 0 else -1.0
        fine = ctrl or shift
        amount = 0.2 if fine else 2.0
        delta = steps * amount
        if ctrl and shift:
            change_x = True
            change_y = True
        elif ctrl:
            change_x = True
            change_y = False
        elif shift:
            change_x = False
            change_y = True
        else:
            change_x = True
            change_y = True
        if change_x:
            self.settings.spacing_x = max(
                self.settings.min_spacing,
                min(self.settings.max_spacing, self.settings.spacing_x + delta),
            )
        if change_y:
            self.settings.spacing_y = max(
                self.settings.min_spacing,
                min(self.settings.max_spacing, self.settings.spacing_y + delta),
            )
        self.status_text = (
            f"X {self.settings.spacing_x:.1f}px · Y {self.settings.spacing_y:.1f}px"
        )
        self.settings.save()
        self.panel.sync_from_settings()
        self.update()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        amount = 5.0 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1.0
        if key == Qt.Key.Key_Left:
            self.settings.offset_x -= amount
        elif key == Qt.Key.Key_Right:
            self.settings.offset_x += amount
        elif key == Qt.Key.Key_Up:
            self.settings.offset_y -= amount
        elif key == Qt.Key.Key_Down:
            self.settings.offset_y += amount
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.set_locked(True)
            return
        elif key == Qt.Key.Key_Escape:
            self.close_requested.emit()
            return
        else:
            super().keyPressEvent(event)
            return
        self.status_text = (
            f"위치 X {self.settings.offset_x:.0f}px · Y {self.settings.offset_y:.0f}px"
        )
        self.settings.save()
        self.update()

    def apply_panel_settings(self) -> None:
        self.settings.save()
        self.update()

    def closeEvent(self, event) -> None:
        self.panel.close()
        super().closeEvent(event)


class WheelPad(QLabel):
    wheel_moved = Signal(int, bool, bool, bool)

    def __init__(self) -> None:
        super().__init__("여기에 마우스를 올리고 휠\nX/Y 간격 조절")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(58)
        self.setStyleSheet(
            "background: #353535; color: white; border: 1px solid #9a9a9a; "
            "border-radius: 5px; padding: 5px;"
        )

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y()
        if not delta:
            return
        ctrl, shift, alt = wheel_modifier_states(event)
        self.wheel_moved.emit(
            delta,
            ctrl,
            shift,
            alt,
        )
        event.accept()


class DragHandle(QLabel):
    def __init__(self, panel: QWidget) -> None:
        super().__init__("그리드 설정  ·  드래그해서 이동", panel)
        self.panel = panel
        self.drag_offset: QPoint | None = None
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setStyleSheet(
            "background: #202020; color: white; border: 1px solid #777; "
            "border-radius: 4px; padding: 6px; font-weight: bold;"
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_offset = event.globalPosition().toPoint() - self.panel.pos()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self.drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.panel.move(event.globalPosition().toPoint() - self.drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_offset = None
            event.accept()
            return
        super().mouseReleaseEvent(event)


class SettingsPanel(QFrame):
    def __init__(self, overlay: GridOverlay) -> None:
        super().__init__(overlay)
        self.overlay = overlay
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setObjectName("settingsPanel")
        self.setStyleSheet(
            "#settingsPanel { background: rgba(25, 25, 25, 225); "
            "border: 1px solid #777; border-radius: 6px; color: white; }"
            "QLabel, QCheckBox { color: white; }"
        )
        self.setFixedWidth(280)

        self.x_spin = self._spacing_spin()
        self.y_spin = self._spacing_spin()
        self.x_spin.valueChanged.connect(self._values_changed)
        self.y_spin.valueChanged.connect(self._values_changed)

        self.major_check = QCheckBox("주선 표시")
        self.major_check.toggled.connect(self._values_changed)
        self.major_every = QSpinBox()
        self.major_every.setRange(2, 20)
        self.major_every.setSuffix(" 줄마다")
        self.major_every.valueChanged.connect(self._values_changed)

        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(20, 255)
        self.opacity.valueChanged.connect(self._values_changed)

        self.color_button = QPushButton("선 색상 선택")
        self.color_button.clicked.connect(self._choose_color)
        self.close_button = QPushButton("그리드 닫기 (Esc)")
        self.close_button.clicked.connect(self.overlay.close_requested.emit)
        self.reselect_button = QPushButton("새 영역 선택")
        self.reselect_button.clicked.connect(self.overlay.new_selection_requested.emit)
        self.wheel_pad = WheelPad()
        self.wheel_pad.wheel_moved.connect(self.overlay.adjust_spacing)
        self.drag_handle = DragHandle(self)

        form = QFormLayout()
        form.addRow("X 간격", self.x_spin)
        form.addRow("Y 간격", self.y_spin)
        form.addRow(self.major_check, self.major_every)
        form.addRow("선 투명도", self.opacity)
        form.addRow("색상", self.color_button)

        hint = QLabel("휠: X/Y · Ctrl+휠: X · Shift+휠: Y · Ctrl+Shift: 미세")
        hint.setWordWrap(True)
        buttons = QHBoxLayout()
        buttons.addWidget(self.reselect_button)
        buttons.addWidget(self.close_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.drag_handle)
        layout.addLayout(form)
        layout.addWidget(self.wheel_pad)
        layout.addWidget(hint)
        layout.addLayout(buttons)

    def _spacing_spin(self) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(4.0, 200.0)
        spin.setDecimals(1)
        spin.setSingleStep(1.0)
        spin.setSuffix(" px")
        return spin

    def sync_from_settings(self) -> None:
        widgets = (self.x_spin, self.y_spin, self.major_check, self.major_every, self.opacity)
        for widget in widgets:
            widget.blockSignals(True)
        self.x_spin.setValue(self.overlay.settings.spacing_x)
        self.y_spin.setValue(self.overlay.settings.spacing_y)
        self.major_check.setChecked(self.overlay.settings.major_enabled)
        self.major_every.setValue(self.overlay.settings.major_every)
        self.major_every.setEnabled(self.overlay.settings.major_enabled)
        self.opacity.setValue(self.overlay.settings.line_opacity)
        self._update_color_button()
        for widget in widgets:
            widget.blockSignals(False)

    def _values_changed(self, *_args) -> None:
        settings = self.overlay.settings
        settings.spacing_x = self.x_spin.value()
        settings.spacing_y = self.y_spin.value()
        settings.major_enabled = self.major_check.isChecked()
        settings.major_every = self.major_every.value()
        settings.line_opacity = self.opacity.value()
        self.major_every.setEnabled(settings.major_enabled)
        self.overlay.status_text = (
            f"X {settings.spacing_x:.1f}px · Y {settings.spacing_y:.1f}px · Esc 닫기"
        )
        self.overlay.apply_panel_settings()

    def _choose_color(self) -> None:
        color = QColorDialog.getColor(QColor(self.overlay.settings.line_color), self)
        if not color.isValid():
            return
        self.overlay.settings.line_color = color.name()
        self._update_color_button()
        self.overlay.apply_panel_settings()

    def _update_color_button(self) -> None:
        color = self.overlay.settings.line_color
        self.color_button.setStyleSheet(
            f"background-color: {color}; color: {'black' if QColor(color).lightness() > 150 else 'white'};"
        )


class AppController(QObject):
    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self.app = app
        self.settings = Settings.load()
        self.selector: RegionSelector | None = None
        self.shade: ShadeOverlay | None = None
        self.grid: GridOverlay | None = None
        self.tray = self._create_tray()
        self.signals = HotkeySignals()
        self.signals.new_selection.connect(self.start_selection)
        self.signals.toggle_edit.connect(self.toggle_edit)
        self.signals.registration_failed.connect(self.show_warning)
        self.hotkeys = WindowsHotkeyThread(self.signals)
        self.hotkeys.start()

    def _create_tray(self) -> QSystemTrayIcon:
        tray = QSystemTrayIcon(
            self.app.style().standardIcon(QStyle.StandardPixmap.SP_DesktopIcon)
        )
        menu = QMenu()
        menu.addAction("새 영역 선택 (F8)", self.start_selection)
        menu.addAction("편집/잠금 전환 (Ctrl+Shift+E)", self.toggle_edit)
        menu.addSeparator()
        menu.addAction("오버레이 닫기", self.close_overlay)
        menu.addAction("프로그램 종료", self.quit)
        tray.setContextMenu(menu)
        tray.setToolTip("Grid Overlay · F8로 시작")
        tray.show()
        return tray

    def show_warning(self, message: str) -> None:
        self.tray.showMessage(APP_NAME, message, QSystemTrayIcon.MessageIcon.Warning, 5000)

    def start_selection(self) -> None:
        if self.selector is not None:
            self.selector.close()
            self.selector.deleteLater()
        self.selector = RegionSelector()
        self.selector.selected.connect(self.finish_selection)
        self.selector.cancelled.connect(self.cancel_selection)
        self.selector.show()
        self.selector.raise_()
        self.selector.activateWindow()
        self.selector.setFocus()

    def cancel_selection(self) -> None:
        if self.selector:
            self.selector.close()
            self.selector.deleteLater()
            self.selector = None

    def finish_selection(self, rect: QRect) -> None:
        self.cancel_selection()
        self.close_overlay()
        # 새 그래프 영역마다 약 10칸이 보이도록 초기 간격을 자동 생성합니다.
        self.settings.spacing_x = max(
            self.settings.min_spacing,
            min(self.settings.max_spacing, round(rect.width() / 10.0, 1)),
        )
        self.settings.spacing_y = max(
            self.settings.min_spacing,
            min(self.settings.max_spacing, round(rect.height() / 10.0, 1)),
        )
        self.settings.offset_x = 0.0
        self.settings.offset_y = 0.0
        self.settings.save()
        self.shade = ShadeOverlay(rect, self.settings.outside_opacity)
        self.shade.show()
        self.grid = GridOverlay(rect, self.settings)
        self.grid.close_requested.connect(self.close_overlay)
        self.grid.new_selection_requested.connect(self.start_reselection)
        self.grid.show_editing()

    def start_reselection(self) -> None:
        self.close_overlay()
        self.start_selection()

    def toggle_edit(self) -> None:
        if self.grid is None:
            self.start_selection()
            return
        self.grid.set_locked(not self.grid.locked)

    def close_overlay(self) -> None:
        for widget_name in ("grid", "shade"):
            widget = getattr(self, widget_name)
            if widget is not None:
                widget.close()
                widget.deleteLater()
                setattr(self, widget_name, None)

    def quit(self) -> None:
        self.hotkeys.stop()
        self.close_overlay()
        self.cancel_selection()
        self.tray.hide()
        self.app.quit()


def main() -> int:
    if sys.platform != "win32":
        print("현재 MVP는 Windows 전용입니다.")
        return 1
    logging.basicConfig(
        filename=LOG_PATH,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    controller = AppController(app)
    app.aboutToQuit.connect(controller.hotkeys.stop)
    controller.tray.showMessage(
        APP_NAME,
        "실행되었습니다. F8을 눌러 영역을 선택하세요.",
        QSystemTrayIcon.MessageIcon.Information,
        3000,
    )
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
