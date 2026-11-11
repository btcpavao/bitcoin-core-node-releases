"""Node Guide reader adapted from Vault Guide at 9e9486742191d27b8571292034187c3079a9fd60.
Retains its sidebar, responsive chapter picker, typography and local figure rendering.
"""
from html import escape
from PySide6.QtCore import Qt, QTimer, QUrl, QEvent, QSize, QRect
from PySide6.QtGui import QFont, QTextOption, QTextDocument, QTextTable, QIcon, QFontMetrics
from PySide6.QtWidgets import (QDialog, QComboBox, QHBoxLayout, QLabel,
    QListWidget, QPushButton, QTextBrowser, QVBoxLayout)
from guide_visuals import render_visual

STYLE = '''
QWidget { background: #0b0b0b; color: #f2f2f2; }
QListWidget { background: #121212; border: 1px solid #333; border-radius: 8px; padding: 6px; }
QListWidget::item { padding: 10px 8px; }
QListWidget::item:selected { background: #2a2a2a; color: white; }
QTextBrowser { background: #111; border: 1px solid #333; border-radius: 8px; padding: 20px; }
QLabel#Title { font-size: 30px; font-weight: 700; }
QLabel#Subtitle { color: #aaa; }
QPushButton, QComboBox { background:#202020; color:#f2f2f2; border:1px solid #666; border-radius:6px; padding:8px 14px; }
QPushButton:checked { background:#24394a; border:2px solid #8ecbff; padding:7px 13px; }
QPushButton:focus, QComboBox:focus { border:2px solid #f2f2f2; padding:7px 13px; }
QPushButton:hover { background:#2c2c2c; }
QComboBox { combobox-popup:0; selection-background-color:#343434; selection-color:#fff; }
QComboBox QAbstractItemView {
    background:#121212; color:#fff; border:1px solid #4a4a4a;
    border-radius:0px; padding:4px; outline:0;
    selection-background-color:#343434; selection-color:#fff;
}
QComboBox QAbstractItemView::item:selected { background:#343434; color:#fff; }
QComboBoxPrivateContainer { background:#121212; border:1px solid #4a4a4a; padding:0px; }

'''


# Reading sizes are explicit so the desktop's compact UI font cannot shrink prose.
BODY_FONT = QFont('DejaVu Sans', 14)
UI_FONT = QFont('DejaVu Sans', 13)
DOCUMENT_STYLE = """
h2 { font-size:22pt; font-weight:700; margin-top:0; margin-bottom:24px; }
h3 { font-size:17pt; font-weight:700; margin-top:32px; margin-bottom:14px; }
p, li { line-height:150%; }
p { margin-top:0; margin-bottom:20px; }
ol, ul { margin-top:8px; margin-bottom:24px; }
li { margin-bottom:10px; }
pre { font-family:'DejaVu Sans Mono'; font-size:13pt; white-space:pre-wrap; }
th, td { padding:9px; }
"""

from guide_content import SECTIONS

SECTION_ICONS = {'Start here: Node & Vault': 'bitcoin-ui.png',
 'Device privacy & login': 'icons/settings-login.png',
 'Storage & pruning': 'icons/settings-chain-backup.png',
 'Receiving bitcoin': 'bitcoin-ui.png',
 'Bitcoin Core': 'bitcoin-ui.png',
 'Synchronization': 'bitcoin-ui.png',
 'Status & diagnostics': 'bitcoin-ui.png',
 'Networking': 'icons/settings-network-connections.png',
 'Watch-only wallets': 'bitcoin-ui.png',
 'PSBT transactions': 'icons/settings-chain-backup.png',
 'Backups & recovery': 'icons/settings-chain-backup.png',
 'Blockchain backup': 'icons/settings-chain-backup.png',
 'Watch-only backups': 'bitcoin-ui.png',
 'Core configuration': 'icons/settings-software-updates.png',
 'Node configuration': 'icons/settings-network-connections.png',
 'Encrypt & Decrypt Files': 'icons/decrypt-files.png',
 'Persistent storage': 'icons/settings-chain-backup.png',
 'Updates': 'icons/settings-software-updates.png',
 'Troubleshooting': 'icons/settings-chain-backup.png'}


class Guide(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Node Guide')
        self.resize(1180, 760)
        self.setStyleSheet(STYLE)
        self.render_key = None
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self.render_section)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 20)
        outer.setSpacing(10)
        title = QLabel('Node Guide')
        title.setObjectName('Title')
        outer.addWidget(title)
        sub = QLabel('Import Vault’s public wallet, receive, prepare PSBTs and keep this Node recoverable.')
        sub.setObjectName('Subtitle')
        sub.setFont(UI_FONT)
        sub.setWordWrap(True)
        outer.addWidget(sub)
        self.section_picker = QComboBox()
        self.section_picker.setFont(UI_FONT)
        self.section_picker.setAccessibleName('Guide chapter')
        self.section_picker.addItems(list(SECTIONS))
        self.section_picker.hide()
        outer.addWidget(self.section_picker)
        body = QHBoxLayout()
        body.setSpacing(16)
        self.nav = QListWidget()
        self.nav.setFont(UI_FONT)
        self.nav.setFixedWidth(320)
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.nav.setTextElideMode(Qt.ElideNone)
        self.nav.setWordWrap(True)
        self.nav.setAccessibleName('Guide chapters')
        self.nav.addItems(list(SECTIONS))
        from ui import branding_file
        self.nav.setIconSize(QSize(26,26))
        for row,section in enumerate(SECTIONS):
            self.nav.item(row).setIcon(QIcon(str(branding_file(SECTION_ICONS[section]))))
        self.viewer = QTextBrowser()
        self.viewer.setAccessibleName('Guide chapter and illustration description')
        self.viewer.viewport().installEventFilter(self)
        self.nav.viewport().installEventFilter(self)
        self.viewer.setSearchPaths([str(branding_file("GUIDE.html").parent)])
        self.viewer.setOpenExternalLinks(False)
        self.viewer.setOpenLinks(False)
        self.viewer.setFont(BODY_FONT)
        self.viewer.document().setDefaultFont(BODY_FONT)
        self.viewer.document().setDefaultStyleSheet(DOCUMENT_STYLE)
        self.viewer.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        reader = QVBoxLayout()
        reader.setSpacing(12)
        reader.addWidget(self.viewer, 1)
        body.addWidget(self.nav)
        body.addLayout(reader, 1)
        outer.addLayout(body, 1)
        self.nav.currentRowChanged.connect(self.select_section)
        self.section_picker.currentIndexChanged.connect(self.nav.setCurrentRow)
        close = QPushButton('Close')
        close.setFont(UI_FONT)
        close.clicked.connect(self.accept)
        outer.addWidget(close, alignment=Qt.AlignRight)
        self.nav.setCurrentRow(0)

    def select_section(self, row):
        if row < 0:
            return
        self.section_picker.setCurrentIndex(row)
        self._render_timer.start(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'nav'):
            compact = self.width() < 1000
            self.nav.setVisible(not compact)
            self.section_picker.setVisible(compact)
            self._render_timer.start(40)

    def eventFilter(self, watched, event):
        # A vertical scrollbar changes the reader width after setHtml(), even
        # when the dialog itself has not resized. Reflow the figure at that width.
        if watched in (self.viewer.viewport(), self.nav.viewport()) and event.type() == QEvent.Type.Resize:
            self._render_timer.start(40)
        return super().eventFilter(watched, event)

    def fit_chapter_labels(self):
        width = self.nav.viewport().width()
        metrics = QFontMetrics(self.nav.font())
        text_width = max(80, width - self.nav.iconSize().width() - 40)
        for row in range(self.nav.count()):
            item = self.nav.item(row)
            bounds = metrics.boundingRect(QRect(0, 0, text_width, 1000), Qt.TextWordWrap, item.text())
            size = QSize(width, max(self.nav.iconSize().height(), bounds.height()) + 20)
            if item.sizeHint() != size:
                item.setSizeHint(size)

    def render_section(self):
        self.fit_chapter_labels()
        row = self.nav.currentRow()
        if row < 0:
            return
        section = list(SECTIONS)[row]
        # Vector commands are rendered at display size and device scale;
        # labels reflow instead of shrinking when the window gets narrower.
        available = int(self.viewer.viewport().width() - 2 * self.viewer.document().documentMargin() - 48)
        width = min(960, max(490, available))
        key = (section, width, self.devicePixelRatioF())
        if key == self.render_key:
            return
        scroll = self.viewer.verticalScrollBar().value() if self.render_key and self.render_key[0] == section else 0
        svg, width, height, title, description, image = render_visual(
            section, width, self.devicePixelRatioF())
        resource = QUrl('node-guide:illustration')
        self.viewer.document().addResource(QTextDocument.ResourceType.ImageResource, resource, image)
        source = SECTIONS[section]
        split = source.index('</h2>') + len('</h2>')
        figure = ('<h3>' + escape(title) + '</h3>'
                  '<p style="line-height:100%;margin-bottom:16px"><img src="node-guide:illustration" width="' + str(width) +
                  '" height="' + str(height) + '" alt="' + escape(description, quote=True) + '"></p>'
                  '<p style="color:#c4c4c4;margin-bottom:24px">' + escape(description) + '</p>')
        content = source[:split] + figure + source[split:]
        self.viewer.setHtml(content)
        # QTextBrowser does not apply CSS table margins like a web browser.
        # Give each native table frame room above and below its border instead.
        for frame in self.viewer.document().rootFrame().childFrames():
            if isinstance(frame, QTextTable):
                table_format = frame.format()
                table_format.setTopMargin(16)
                table_format.setBottomMargin(24)
                frame.setFormat(table_format)
        self.viewer.verticalScrollBar().setValue(scroll)
        self.render_key = key
        self.current_svg = svg
        self.current_description = description
