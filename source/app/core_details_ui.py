"""Independent, searchable local Core snapshot. Never connects to remote telemetry."""
import json
import time
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QTreeWidget, QTreeWidgetItem, QTabWidget, QPlainTextEdit,
    QPushButton, QHeaderView)

GROUP_NAMES = {'chain': 'Blockchain', 'net': 'Network and software',
               'mempool': 'Mempool', 'transports': 'Peer networks',
               'transport_protocols': 'Peer transport protocols',
               'wallet_rescans': 'Wallet rescans'}


class TechnicalDetailsDialog(QDialog):
    def __init__(self, data=None):
        super().__init__(None)
        from ui import STYLE
        self.setStyleSheet(STYLE)
        self.setWindowTitle('Bitcoin Core Technical Details')
        self.setWindowFlag(Qt.WindowMinimizeButtonHint, True)
        self.resize(980, 700)
        self.job = None
        self.closing = False
        self.data = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 16)
        heading = QLabel('Bitcoin Core Technical Details')
        heading.setObjectName('Title')
        heading.setWordWrap(True)
        layout.addWidget(heading)
        note = QLabel('Local snapshot. Review it at your own pace; Refresh fetches a new snapshot. Wallet names and other diagnostics may be private.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.updated = QLabel()
        self.updated.setObjectName('Muted')
        layout.addWidget(self.updated)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Find a field or value…')
        self.search.setAccessibleName('Search technical details')
        layout.addWidget(self.search)
        self.tabs = QTabWidget()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['Field', 'Value'])
        self.tree.setAccessibleName('Grouped Bitcoin Core technical details')
        self.tree.setAlternatingRowColors(False)
        self.tree.setWordWrap(True)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Interactive)
        self.tree.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tree.setColumnWidth(0, 280)
        self.tabs.addTab(self.tree, 'Grouped details')
        self.raw = QPlainTextEdit()
        self.raw.setReadOnly(True)
        self.raw.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.raw.setAccessibleName('Raw local status JSON')
        self.tabs.addTab(self.raw, 'Raw JSON')
        layout.addWidget(self.tabs, 1)
        self.search.textChanged.connect(self.filter_tree)
        self.tabs.currentChanged.connect(lambda index: self.search.setVisible(index == 0))
        actions = QHBoxLayout()
        expand = QPushButton('Expand all')
        expand.clicked.connect(self.tree.expandAll)
        collapse = QPushButton('Collapse all')
        collapse.clicked.connect(self.tree.collapseAll)
        copy = QPushButton('Copy snapshot')
        copy.setToolTip('Copy the displayed diagnostics to the clipboard. Review private information before sharing.')
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.raw.toPlainText()))
        actions.addWidget(expand)
        actions.addWidget(collapse)
        actions.addWidget(copy)
        actions.addStretch()
        self.refresh_button = QPushButton('Refresh')
        self.refresh_button.clicked.connect(self.refresh)
        actions.addWidget(self.refresh_button)
        close = QPushButton('Close')
        close.clicked.connect(self.reject)
        actions.addWidget(close)
        layout.addLayout(actions)
        self.apply(data or {'available': False, 'service': 'Not checked', 'updated': time.time()})

    def apply(self, data):
        if self.closing:
            return
        self.data = data
        self.raw.setPlainText(json.dumps(data, indent=2, ensure_ascii=False))
        self.tree.clear()
        overview = QTreeWidgetItem(self.tree, ['Overview', ''])

        def add(parent, name, value):
            if isinstance(value, (dict, list)):
                node = QTreeWidgetItem(parent, [str(name), f'{len(value)} entries'])
                pairs = value.items() if isinstance(value, dict) else enumerate(value)
                for key, child in pairs:
                    add(node, key, child)
                return node
            text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
            node = QTreeWidgetItem(parent, [str(name), text])
            node.setToolTip(1, text)
            return node

        for key, value in data.items():
            if key in GROUP_NAMES:
                node = add(self.tree, GROUP_NAMES[key], value)
                node.setExpanded(True)
            else:
                add(overview, key, value)
        overview.setExpanded(True)
        self.updated.setText('Snapshot: ' + time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(data.get('updated', time.time()))))
        self.filter_tree(self.search.text())

    def filter_tree(self, text):
        needle = text.casefold().strip()

        def visit(item, inherited=False):
            match = inherited or not needle or needle in (item.text(0) + ' ' + item.text(1)).casefold()
            descendants = [visit(item.child(i), match) for i in range(item.childCount())]
            visible = match or any(descendants)
            item.setHidden(not visible)
            if needle and visible and item.childCount():
                item.setExpanded(True)
            return visible

        for i in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(i))

    def refresh(self):
        if self.job is not None or self.closing:
            return
        from core_status_ui import Worker
        self.refresh_button.setEnabled(False)
        self.job = Worker(self)
        self.job.received.connect(self.apply)
        self.job.finished.connect(self.finished_poll)
        self.job.start()

    def finished_poll(self):
        job = self.job
        self.job = None
        job.deleteLater()
        self.refresh_button.setEnabled(True)
        if self.closing:
            super().reject()

    def reject(self):
        self.closing = True
        if self.job is not None:
            self.hide()
        else:
            super().reject()

    def closeEvent(self, event):
        if self.job is not None:
            self.reject()
            event.ignore()
        else:
            super().closeEvent(event)
