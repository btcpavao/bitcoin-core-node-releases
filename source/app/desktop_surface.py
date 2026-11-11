"""Desktop widgets carried over from Bitcoin Core Vault; see installer/VAULT-ORIGIN.json."""
from __future__ import annotations
import argparse
import fcntl
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
from PySide6.QtCore import Qt, QSize, QTimer, QRect, QRectF, QPoint
from PySide6.QtGui import QFont, QIcon, QPixmap, QImage, QPainter
from PySide6.QtWidgets import (
    QApplication, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QScrollArea, QStyle, QVBoxLayout, QWidget,
)
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QAbstractButton, QScrollBar

VERSION = 'home-suite-v1'

HOVER_DELAY_MS = 800

STYLE = '''
QWidget#VaultSurface { background-color: #000000; }
QLabel { background: transparent; border: none; color: #ffffff; }
QWidget#CenterBody, QWidget#Header, QWidget#CardGrid, QWidget#Footer,
QWidget#CreditBox, QWidget#FooterSpacer, QWidget#PowerControls,
QWidget#PowerInfo, QWidget#PowerIconRow { background: transparent; }
QScrollArea#CenterScroll { background: transparent; border: none; }
QLabel#MainTitle { font-size: 28px; font-weight: 700; }
QLabel#MainSubtitle { font-size: 14px; color: #a8a8a8; }
QPushButton#ToolCard {
    background: #151515; border: 1px solid #333333; border-radius: 10px;
    padding: 0px;
}
QPushButton#ToolCard:hover { background: #202020; border-color: #555555; }
QPushButton#ToolCard:pressed { background: #101010; }
QPushButton#ToolCard:focus { border-color: #f7931a; }
QPushButton#ToolCard:disabled { background: #101010; border-color: #222222; }
QPushButton#ToolCard QLabel { background: transparent; border: none; }
QLabel#CardTitle { font-size: 14px; font-weight: 600; }
QLabel#CardDescription { font-size: 11px; color: #a8a8a8; }
QLabel#CardTitle:disabled, QLabel#CardDescription:disabled { color: #777777; }
QFrame#HoverPopup {
    background: #191919; border: 1px solid #484848; border-radius: 8px;
}
QLabel#HoverText {
    background: transparent; color: #f0f0f0; font-size: 12px;
}
QLabel#Credit { font-size: 12px; color: #999999; }
QPushButton#Shutdown, QPushButton#Restart, QPushButton#NetworkStatus {
    background: transparent; border: 1px solid transparent;
    border-radius: 24px; padding: 0px;
}
QPushButton#Shutdown:hover, QPushButton#Restart:hover, QPushButton#NetworkStatus:hover { background: #202020; }
QPushButton#Shutdown:focus, QPushButton#Restart:focus, QPushButton#NetworkStatus:focus { border-color: #b7dafa; }
/* VAULT_HOME_DARK_DIALOGS_V1: Home-owned dialogs inherit this scoped theme. */
QMessageBox { background-color: #191919; color: #f0f0f0; }
QMessageBox QLabel { background: transparent; color: #f0f0f0; }
QMessageBox QPushButton {
    background-color: #272727; color: #ffffff; border: 1px solid #555555;
    border-radius: 5px; padding: 6px 16px; min-width: 72px;
}
QMessageBox QPushButton:hover { background-color: #333333; }
QMessageBox QPushButton:pressed { background-color: #202020; }
QMessageBox QPushButton:default, QMessageBox QPushButton:focus {
    border-color: #b7dafa;
}
'''

def icon_for(names, fallback):
    for name in names:
        result = QIcon.fromTheme(name)
        if not result.isNull():
            return result
    return QApplication.style().standardIcon(fallback)

def icon_bounds(image):
    left, top, right, bottom = image.width(), image.height(), -1, -1
    mass = 0.0
    for y in range(image.height()):
        for x in range(image.width()):
            alpha = image.pixelColor(x, y).alpha()
            if alpha >= 16:
                left, top = min(left, x), min(top, y)
                right, bottom = max(right, x), max(bottom, y)
                mass += alpha / 255.0
    if right < left:
        return QRect(), 0.0
    return QRect(left, top, right-left+1, bottom-top+1), mass

def optical_icon(icon, size=42):
    # Some hicolor icons contain padding or only a small raster. Render high,
    # trim transparent padding, then scale the visible mark without distortion.
    image = icon.pixmap(QSize(128, 128), QIcon.Normal, QIcon.Off).toImage()
    bounds, mass = icon_bounds(image)
    out = QPixmap(size*2, size*2)
    out.fill(Qt.transparent)
    if bounds.isEmpty():
        out.setDevicePixelRatio(2.0)
        return out
    image = image.copy(bounds)
    # Equal ink area where practical; cap each dimension to a common 38 px box.
    edge = size * (38 / 42)
    ink = 980 * (size / 42)**2
    scale = min(edge/image.width(), edge/image.height(), math.sqrt(ink/max(mass, 1)))
    width, height = image.width()*scale, image.height()*scale
    painter = QPainter(out)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    painter.drawImage(QRectF(size-width, size-height, width*2, height*2), image)
    painter.end()
    out.setDevicePixelRatio(2.0)
    return out

def power_icon(restart, assets):
    filename = 'system-reboot.png' if restart else 'system-shutdown.png'
    path = assets / 'icons' / filename
    if not path.is_file():
        raise RuntimeError('Missing bundled power icon: ' + str(path))
    return QIcon(str(path))

def image_label(path, size):
    label = QLabel()
    label.setAlignment(Qt.AlignCenter)
    label.setFixedSize(*size)
    pix = QPixmap(str(path))
    if not pix.isNull():
        label.setPixmap(pix.scaled(*size, Qt.KeepAspectRatio,
                                  Qt.SmoothTransformation))
    return label

class Card(QPushButton):
    def __init__(self, tool, icon, enabled, show_help, hide_help):
        super().__init__()
        self.tool = tool
        self.help_text = tool['help']
        self.show_help_callback = show_help
        self.hide_help_callback = hide_help
        self.setObjectName('ToolCard')
        self.setAccessibleName(tool['title'])
        self.setAccessibleDescription(tool['description'] + '. ' + tool['help'])
        self.setCursor(Qt.PointingHandCursor if enabled else Qt.ArrowCursor)
        self.setEnabled(enabled)
        self.hover_timer = QTimer(self)
        self.hover_timer.setSingleShot(True)
        self.hover_timer.setInterval(HOVER_DELAY_MS)
        self.hover_timer.timeout.connect(lambda: self.show_help_callback(self))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 9, 8, 9)
        layout.setSpacing(4)
        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setFixedHeight(44)
        self.icon_label.setPixmap(optical_icon(icon))
        self.title_label = QLabel(tool['title'])
        self.title_label.setObjectName('CardTitle')
        self.title_label.setWordWrap(True)
        self.description_label = QLabel(tool['description'])
        self.description_label.setObjectName('CardDescription')
        self.description_label.setWordWrap(True)
        self.description_label.setMinimumHeight(28)
        layout.addStretch(1)
        for label in (self.icon_label, self.title_label, self.description_label):
            label.setAlignment(Qt.AlignCenter)
            label.setAttribute(Qt.WA_TransparentForMouseEvents)
            layout.addWidget(label)
        layout.addStretch(1)

    def enterEvent(self, event):
        self.hover_timer.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hover_timer.stop()
        self.hide_help_callback(self)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        self.hover_timer.stop()
        self.hide_help_callback(self)
        super().mousePressEvent(event)

class HintButton(QPushButton):
    def __init__(self, text, help_text, show_help, hide_help):
        super().__init__(text)
        self.setCursor(Qt.PointingHandCursor)
        self.help_text = help_text
        self.show_help_callback = show_help
        self.hide_help_callback = hide_help
        self.hover_timer = QTimer(self)
        self.hover_timer.setSingleShot(True)
        self.hover_timer.setInterval(HOVER_DELAY_MS)
        self.hover_timer.timeout.connect(lambda: self.show_help_callback(self))

    def enterEvent(self, event):
        self.hover_timer.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hover_timer.stop()
        self.hide_help_callback(self)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        self.hover_timer.stop()
        self.hide_help_callback(self)
        super().mousePressEvent(event)

class DesktopSurface(QWidget):
    def __init__(self, tools, assets, title, subtitle):
        super().__init__()
        self.tools, self.assets, self.title, self.subtitle = tools, assets, title, subtitle
        self.preview = False
        self.self_test = os.environ.get("QT_QPA_PLATFORM") == "offscreen"
        self.setWindowTitle(self.title)
        self.setWindowIcon(QIcon(str(self.assets / 'bitcoin-ui.png')))
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint |
                            Qt.WindowStaysOnBottomHint)
        self.setAttribute(Qt.WA_X11NetWmWindowTypeDesktop, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setObjectName('VaultSurface')
        self.setStyleSheet(STYLE)
        self.preview_windows = []
        self.children_started = []
        self.cards = []
        self._layout_key = None
        # Coalesce the frequent X11 LayoutRequest events generated when peer
        # status changes. Unbounded zero-delay singleShot callbacks could
        # starve mouse handling, and callbacks could outlive a deleted window.
        self.layout_timer = QTimer(self)
        self.layout_timer.setSingleShot(True)
        self.layout_timer.timeout.connect(self.layout_cards)
        self.geometry_timer = QTimer(self)
        self.geometry_timer.setSingleShot(True)
        self.geometry_timer.timeout.connect(self.write_geometry)
        self._test_size = None
        self.screen_ref = QApplication.primaryScreen()
        if self.screen_ref is None:
            raise RuntimeError('No graphical screen is available')
        self.build_ui()
        self.build_hover_popup()
        self.screen_ref.geometryChanged.connect(self.fit_screen)
        self.screen_ref.availableGeometryChanged.connect(self.fit_screen)
        self.fit_screen()
        self.reaper = QTimer(self)
        self.reaper.timeout.connect(self.reap)
        self.reaper.start(1000)

        self._background_action = None
        QApplication.instance().installEventFilter(self)

    def build_ui(self):
        self.outer = QVBoxLayout(self)
        self.outer.setSpacing(0)
        self.scroll = QScrollArea()
        self.scroll.setObjectName('CenterScroll')
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.viewport().setAutoFillBackground(False)
        self.body = QWidget()
        self.body.setObjectName('CenterBody')
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 8, 0, 8)
        self.body_layout.setSpacing(0)
        self.body_layout.addStretch(1)

        self.header = QWidget()
        self.header.setObjectName('Header')
        header = QVBoxLayout(self.header)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        header.addWidget(image_label(self.assets / 'bitcoin-ui.png', (48, 48)),
                         alignment=Qt.AlignCenter)
        title = QLabel(self.title)
        title.setObjectName('MainTitle')
        title.setAlignment(Qt.AlignCenter)
        header.addWidget(title)
        sub = QLabel(self.subtitle)
        sub.setObjectName('MainSubtitle')
        sub.setAlignment(Qt.AlignCenter)
        sub.setWordWrap(True)
        header.addWidget(sub)
        self.body_layout.addWidget(self.header)
        self.body_layout.addSpacing(16)

        self.grid_wrap = QWidget()
        self.grid_wrap.setObjectName('CardGrid')
        self.grid = QGridLayout(self.grid_wrap)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(14)
        self.grid.setVerticalSpacing(14)

        for tool in self.tools:
            icon = icon_for(tool['icons'], tool['fallback'])
            if tool['title'] == 'Bitcoin Core':
                custom = QIcon(str(self.assets / 'bitcoin-ui.png'))
                if not custom.isNull():
                    icon = custom
            elif tool['title'] == 'KeePassXC':
                custom = QIcon('/opt/keepassxc/current/node-icon.png')
                if not custom.isNull():
                    icon = custom
            command = tool['command']
            if command is None:
                enabled = True
            elif self.preview or self.self_test:
                enabled = True
            else:
                enabled = (Path(command[0]).exists() if command[0].startswith('/')
                           else shutil.which(command[0]) is not None)
            card = Card(tool, icon, enabled, self.show_card_help, self.hide_card_help)
            card.clicked.connect(lambda checked=False, c=command, t=tool['title']:
                                 self.activate_tool(t, c))
            self.cards.append(card)

        self.body_layout.addWidget(self.grid_wrap, alignment=Qt.AlignCenter)
        self.body_layout.addStretch(1)
        self.body.installEventFilter(self)
        self.scroll.setWidget(self.body)
        self.outer.addWidget(self.scroll, 1)

        self.footer = QWidget()
        self.footer.setObjectName('Footer')
        # Node right footer: status, time, then network/restart/shutdown buttons.
        # Keep left and right zones equal so the Debian credit stays centered.
        self.footer.setFixedHeight(112)
        footer = QHBoxLayout(self.footer)
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(0)
        # VAULT_POWER_CONTROLS_V1
        # Equal-width left/right footer zones keep Powered by Debian GNU/Linux centered.
        left = QWidget()
        left.setObjectName('FooterSpacer')
        left.setFixedWidth(256)
        footer.addWidget(left)
        self.credit_box = QWidget()
        self.credit_box.setObjectName('CreditBox')
        credit = QVBoxLayout(self.credit_box)
        # Keep the credit horizontally centered, but line up its lower caption
        # with the power controls. The former expanding QLabel spread the
        # Debian icon and caption across the entire 112px footer and made the
        # icon appear much higher than the rest of the footer.
        credit.setContentsMargins(0, 0, 0, 7)
        credit.setSpacing(2)
        credit.addStretch(1)
        self.debian_logo = image_label(self.assets / 'debian-ui.png', (20, 26))
        credit.addWidget(self.debian_logo, 0, Qt.AlignHCenter)
        caption = QLabel('Powered by Debian GNU/Linux')
        self.debian_caption = caption
        caption.setObjectName('Credit')
        caption.setAlignment(Qt.AlignCenter)
        caption.setFixedHeight(18)
        credit.addWidget(caption, 0, Qt.AlignHCenter)
        footer.addWidget(self.credit_box, 1)

        power_box = QWidget()
        self.power_box=power_box
        power_box.setObjectName('PowerControls')
        power_box.setFixedSize(224,110)
        power_stack=QVBoxLayout(power_box)
        power_stack.setContentsMargins(0,0,0,0)
        power_stack.setSpacing(1)
        self.power_info=QWidget(power_box)
        self.power_info.setObjectName('PowerInfo')
        self.power_info.setFixedHeight(55)
        self.power_info_layout=QVBoxLayout(self.power_info)
        self.power_info_layout.setContentsMargins(0,0,0,0)
        self.power_info_layout.setSpacing(1)
        power_stack.addWidget(self.power_info)
        self.power_icon_row=QWidget(power_box)
        self.power_icon_row.setObjectName('PowerIconRow')
        power = QHBoxLayout(self.power_icon_row)
        power.setContentsMargins(0, 0, 0, 0)
        power.setSpacing(8)
        power_stack.addWidget(self.power_icon_row)

        restart_help = 'Restart this computer. Private Workspace is cleared; other saved files remain on disk.'
        # VAULT_POWER_ICON_BUTTONS_V1: retain the existing confirmation/actions.
        power.addStretch(1)
        self.restart_button = HintButton(
            '', restart_help, self.show_card_help, self.hide_card_help)
        self.restart_button.setObjectName('Restart')
        self.restart_button.setAccessibleName('Restart')
        self.restart_button.setAccessibleDescription(restart_help)
        self.restart_button.setIcon(power_icon(True, self.assets))
        self.restart_button.setIconSize(QSize(44, 44))
        self.restart_button.setFixedSize(48, 48)
        self.restart_button.clicked.connect(self.restart)
        power.addWidget(self.restart_button)

        shutdown_help = 'Shut down this computer. Private Workspace is cleared; other saved files remain on disk.'
        self.shutdown_button = HintButton(
            '', shutdown_help, self.show_card_help, self.hide_card_help)
        self.shutdown_button.setObjectName('Shutdown')
        self.shutdown_button.setAccessibleName('Shut down')
        self.shutdown_button.setAccessibleDescription(shutdown_help)
        self.shutdown_button.setIcon(power_icon(False, self.assets))
        self.shutdown_button.setIconSize(QSize(44, 44))
        self.shutdown_button.setFixedSize(48, 48)
        self.shutdown_button.clicked.connect(self.shutdown)
        power.addWidget(self.shutdown_button)
        power.addStretch(1)
        # Both stretches receive the same free width; the three power icons
        # form a centered row exactly below the status and clock.
        footer.addWidget(power_box, 0, Qt.AlignBottom)
        self.outer.addWidget(self.footer)

    def build_hover_popup(self):
        self.hover_popup = QFrame(self)
        self.hover_popup.setObjectName('HoverPopup')
        self.hover_popup.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout = QVBoxLayout(self.hover_popup)
        layout.setContentsMargins(12, 10, 12, 10)
        self.hover_text = QLabel()
        self.hover_text.setObjectName('HoverText')
        self.hover_text.setWordWrap(True)
        self.hover_text.setFixedWidth(310)
        layout.addWidget(self.hover_text)
        self.hover_popup.hide()
        self.hover_card = None

    def show_card_help(self, card):
        if not card.underMouse() and not self.self_test:
            return
        self.hover_card = card
        self.hover_text.setText(card.help_text)
        self.hover_popup.adjustSize()
        p = card.mapTo(self, QPoint(0, 0))
        x = p.x() + (card.width() - self.hover_popup.width()) // 2
        y = p.y() - self.hover_popup.height() - 10
        x = max(10, min(x, self.width() - self.hover_popup.width() - 10))
        if y < 10:
            y = p.y() + card.height() + 10
        y = max(10, min(y, self.height() - self.hover_popup.height() - 10))
        self.hover_popup.move(x, y)
        self.hover_popup.show()
        self.hover_popup.raise_()

    def hide_card_help(self, card=None):
        if card is None or card is self.hover_card:
            self.hover_popup.hide()
            self.hover_card = None

    def schedule_layout(self):
        # One pending geometry pass at a time, parent-owned by the window.
        if not self.layout_timer.isActive():
            self.layout_timer.start(0)

    def fit_screen(self, *_):
        if self._test_size:
            width, height = self._test_size
            geometry = QRect(0, 0, width, height)
            panel = 40
        else:
            geometry = self.screen_ref.geometry()
            available = self.screen_ref.availableGeometry()
            panel = max(0, geometry.bottom() - available.bottom())
            panel = min(panel, geometry.height() // 3)
        if self.geometry() != geometry:
            self.setGeometry(geometry)
        self.outer.setContentsMargins(24, 16, 24, panel + 12)
        self.hide_card_help()
        self.schedule_layout()

    def apply_home_density(self, level):
        # Compact only as much as the available height requires.
        if getattr(self, '_home_density', None) == level:
            return
        self._home_density = level
        logo_size, title_size, subtitle_size, icon_size, card_title, card_detail, margin, spacing, gap = (
            (48, 28, 14, 42, 14, 11, 9, 4, 16),
            (40, 26, 13, 34, 14, 11, 6, 3, 12),
            (28, 22, 12, 28, 12, 10, 4, 2, 8),
            (24, 20, 11, 24, 12, 10, 2, 1, 6),
            (20, 18, 10, 20, 11, 9, 1, 1, 4),
        )[level]
        logo = self.header.layout().itemAt(0).widget()
        if not hasattr(self, '_home_logo'):
            self._home_logo = QPixmap(logo.pixmap())
        logo.setFixedSize(logo_size, logo_size)
        logo.setPixmap(self._home_logo.scaled(logo_size, logo_size,
                                             Qt.KeepAspectRatio, Qt.SmoothTransformation))
        for name, size in (('MainTitle', title_size), ('MainSubtitle', subtitle_size)):
            label = self.header.findChild(QLabel, name)
            label.setStyleSheet('font-size: %dpx;' % size)
        self.header.layout().setSpacing(8 if level == 0 else 2 if level >= 3 else 4)
        header_index = self.body_layout.indexOf(self.header)
        self.body_layout.itemAt(header_index + 1).spacerItem().changeSize(0, gap)
        for card in getattr(self, 'all_home_cards', self.cards):
            layout = card.layout()
            layout.setContentsMargins(8 if level == 0 else 6, margin,
                                      8 if level == 0 else 6, margin)
            layout.setSpacing(spacing)
            card.title_label.setStyleSheet('font-size: %dpx;' % card_title)
            card.description_label.setStyleSheet('font-size: %dpx;' % card_detail)
            card.title_label.ensurePolished()
            card.description_label.ensurePolished()
            if not hasattr(card, '_home_icon'):
                card._home_icon = QPixmap(card.icon_label.pixmap())
            pixmap = card._home_icon.scaled(icon_size * 2, icon_size * 2,
                                           Qt.KeepAspectRatio, Qt.SmoothTransformation)
            pixmap.setDevicePixelRatio(2)
            card.icon_label.setPixmap(pixmap)
            card.icon_label.setFixedHeight(icon_size + (2 if level == 0 else 0))
        if hasattr(self, 'activity_row'):
            if not hasattr(self,'activity_slot'):
                activity_index = self.body_layout.indexOf(self.activity_row)
                self.body_layout.itemAt(activity_index - 1).spacerItem().changeSize(
                    0, 24 if level == 0 else 4 if level >= 3 else 8)
            self.activity_row.layout().setSpacing(8 if level == 0 else 2 if level >= 3 else 4)
            self.activity_text.setStyleSheet(
                'font-style:italic; font-size:%dpx;' % (14 if level == 0 else 12))
            if hasattr(self,'activity_slot'):
                w=min(620,max(300,self.width()-60))
                self.activity_row.setFixedWidth(w)
                self.activity_row.layout().invalidate()
                h=self.activity_row.heightForWidth(w)
                h=max(self.activity_row.minimumSizeHint().height(),h if h>=0 else self.activity_row.sizeHint().height())
                # Leave enough space that the centered meters never meet the
                # right-hand status/clock controls on a 600px-high screen.
                self.activity_slot.setFixedHeight(h+62)
        self.body_layout.invalidate()

    def layout_cards(self):
        viewport = self.scroll.viewport()
        width = max(360, min(1120, viewport.width() - 8))
        columns = 5 if width >= 680 else 2
        card_width = (width - (columns - 1) * 14) // columns
        rows = math.ceil(len(self.cards) / columns)
        feedback = tuple((getattr(self, name).text(), getattr(self, name).isHidden())
                         for name in ('activity_text', 'status') if hasattr(self, name))
        key = (viewport.width(), viewport.height(), len(self.cards), feedback)
        if key == self._layout_key:
            return
        self._layout_key = key
        self.hide_card_help()
        for level in range(5):
            self.apply_home_density(level)
            vertical_margin = 8 if level == 0 and viewport.height() >= 500 else 2
            vertical_gap = (14, 10, 8, 6, 4)[level]
            self.body_layout.setContentsMargins(0, vertical_margin, 0, vertical_margin)
            self.grid.setVerticalSpacing(vertical_gap)
            self.header.layout().invalidate()
            header_height = self.header.heightForWidth(viewport.width())
            if header_height < 0:
                header_height = self.header.sizeHint().height()
            self.header.setFixedHeight(header_height)
            extra = 0
            for index in range(self.body_layout.count()):
                item = self.body_layout.itemAt(index)
                widget = item.widget()
                if widget in (self.header, self.grid_wrap):
                    continue
                if widget is not None:
                    if widget.isHidden() and not widget.sizePolicy().retainSizeWhenHidden():
                        continue
                    height = widget.heightForWidth(viewport.width())
                    extra += max(item.minimumSize().height(),
                                 height if height >= 0 else item.sizeHint().height())
                elif item.spacerItem():
                    extra += item.spacerItem().sizeHint().height()
            minimum_card_height = 0
            for card in self.cards:
                margins = card.layout().contentsMargins()
                text_width = card_width - margins.left() - margins.right()
                card.title_label.setMinimumHeight(0)
                card.description_label.setMinimumHeight(0)
                title_height = card.title_label.heightForWidth(text_width)
                detail_height = card.description_label.heightForWidth(text_width)
                card.title_label.setMinimumHeight(max(title_height, 0))
                card.description_label.setMinimumHeight(max(detail_height, 0))
                card.layout().invalidate()
                minimum_card_height = max(minimum_card_height,
                                          card.layout().minimumSize().height())
            available = (viewport.height() - header_height - extra -
                         2 * vertical_margin - (rows - 1) * vertical_gap)
            card_height = min(144, available // max(rows, 1))
            if card_height >= minimum_card_height:
                break
        # Keep readable content reachable on unusually small displays. Supported
        # laptop sizes fit before this floor; never hide an overflowing scroll.
        card_height = max(minimum_card_height, card_height)
        while self.grid.count():
            self.grid.takeAt(0)
        for index, card in enumerate(self.cards):
            card.setFixedSize(card_width, card_height)
            row = index // columns
            row_count = min(columns, len(self.cards) - row * columns)
            offset = columns - row_count
            self.grid.addWidget(card, row, 2 * (index % columns) + offset, 1, 2)
        self.grid_wrap.setFixedSize(columns * card_width + (columns - 1) * 14,
                                    rows * card_height + (rows - 1) * vertical_gap)
        self.body.setMinimumHeight(header_height + extra +
                                   self.grid_wrap.height() + 2 * vertical_margin)
        self.body_layout.invalidate()
        self.geometry_timer.start(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.hide_card_help()
        self.schedule_layout()

    def closeEvent(self, event):
        event.ignore()

    def write_geometry(self):
        if self.self_test:
            return
        runtime = os.environ.get('XDG_RUNTIME_DIR')
        if not runtime:
            return
        def rect(r):
            return [r.x(), r.y(), r.width(), r.height()]
        obj = {'version': VERSION, 'pid': os.getpid(), 'window_id': hex(int(self.winId())),
               'desktop_geometry': rect(self.geometry()),
               'screen_geometry': rect(self.screen_ref.geometry()),
               'available_geometry': rect(self.screen_ref.availableGeometry()),
               'card_sizes': [[c.width(), c.height()] for c in self.cards],
               'card_titles': [c.tool['title'] for c in self.cards]}
        obj['window_behavior'] = 'background-click-v1.2'
        obj['card_rects'] = [
            [c.mapTo(self, QPoint(0, 0)).x(), c.mapTo(self, QPoint(0, 0)).y(),
             c.width(), c.height()] for c in self.cards]
        try:
            (Path(runtime) / 'core-node-desktop-geometry.json').write_text(
                json.dumps(obj, indent=2) + '\n')
        except OSError as exc:
            print(f'Geometry report unavailable: {exc}', file=sys.stderr)

    def activate_tool(self, title, command):
        raise NotImplementedError("The product supplies this action.")

    def reap(self):
        self.children_started = [p for p in self.children_started if p.poll() is None]


    def power_question(self, title, message, button):
        raise NotImplementedError("The product supplies this action.")

    def restart(self):
        raise NotImplementedError("The product supplies this action.")

    def shutdown(self):
        raise NotImplementedError("The product supplies this action.")

    # VAULT_BACKGROUND_CLICK_V12
    def _home_control_at(self, widget, position=None):
        # Disabled cards must also remain controls, even when Qt routes their
        # mouse events to a parent. Check their rectangles as well as ancestry.
        if position is not None:
            for card in self.cards:
                if card.isVisible() and QRect(card.mapTo(self, QPoint(0, 0)),
                                               card.size()).contains(position):
                    return True
        current = widget if isinstance(widget, QWidget) else None
        while current is not None and current is not self:
            if isinstance(current, (QAbstractButton, QScrollBar)):
                return True
            current = current.parentWidget()
        return False

    def _belongs_to_home(self, widget):
        # In preview, other application-like windows live in the same process.
        # Never treat a click inside those top-level windows as a desktop click.
        return isinstance(widget, QWidget) and widget.window() is self

    def show_home_from_background_click(self):
        self.hide_card_help()
        if self.self_test:
            return
        # Never iconify a Qt modal child of Home. Doing so can leave an invisible
        # application-modal dialog holding Qt's input guard, making every
        # launcher button appear frozen even after Bitcoin Core exits.
        if (QApplication.activeModalWidget() is not None or
            any(isinstance(w, QDialog) and w.isModal() and w.isVisible()
                for w in QApplication.topLevelWidgets())):
            return
        if self._background_action is not None and self._background_action.poll() is None:
            return
        helper = Path('/usr/local/bin/core-node-show-home')
        try:
            self._background_action = subprocess.Popen(
                [sys.executable, str(helper), '--home-window', str(int(self.winId()))],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                start_new_session=True,
            )
            self.children_started.append(self._background_action)
        except OSError as exc:
            print('Vault background click:', exc, file=sys.stderr)

    def eventFilter(self, watched, event):
        if watched is self.body and event.type() == QEvent.LayoutRequest:
            self.schedule_layout()
        if (event.type() == QEvent.MouseButtonPress
                and event.button() == Qt.LeftButton
                and self._belongs_to_home(watched)):
            position = self.mapFromGlobal(event.globalPosition().toPoint())
            if not self._home_control_at(watched, position):
                self.show_home_from_background_click()
                # Consume this event so propagation through the scroll area,
                # body and desktop cannot trigger the action several times.
                return True
        return super().eventFilter(watched, event)
