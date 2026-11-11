"""Native Qt watch-only balance and address management."""
import hashlib
import base64
import json
from pathlib import Path
from decimal import Decimal

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog,
    QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QAbstractItemView, QHeaderView, QScrollArea, QWidget, QLayout)

from wallets import WalletService, WalletError, amount


class WorkDialog(QDialog):
    def __init__(self, parent, title):
        super().__init__(parent)
        from ui import STYLE
        self.setWindowTitle(title); self.setStyleSheet(STYLE); self.resize(840, 680)
        self.service = WalletService(parent.rpc); self.job = None; self.actions = []
        outer = QVBoxLayout(self); outer.setContentsMargins(24, 24, 24, 24); outer.setSpacing(14)
        heading = QLabel(title); heading.setObjectName('Title'); outer.addWidget(heading)
        self.status = QLabel(''); self.status.setWordWrap(True); self.status.setTextFormat(Qt.PlainText)
        outer.addWidget(self.status)
        body = QWidget(); self.layout = QVBoxLayout(body); self.layout.setSpacing(12)
        self.layout.setSizeConstraint(QLayout.SetMinimumSize)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(body); outer.addWidget(scroll, 1)

    def text(self, label):
        widget = QPlainTextEdit(); widget.setReadOnly(True); widget.setAccessibleName(label); widget.setMinimumHeight(160)
        self.layout.addWidget(widget, 1); return widget

    def button(self, label, action, layout=None):
        button = QPushButton(label); button.clicked.connect(action)
        (layout or self.layout).addWidget(button); self.actions.append(button); return button

    def run(self, fn, done, message='Working…'):
        if self.job and self.job.isRunning(): return
        from ui import Job
        self.status.setText(message)
        for button in self.actions: button.setEnabled(False)
        self.job = Job(fn, self)
        self.job.success.connect(done); self.job.failure.connect(self.status.setText)
        self.job.finished.connect(self.finish); self.job.start()

    def finish(self):
        for button in self.actions: button.setEnabled(True)
        self.refresh_actions()

    def refresh_actions(self): pass

    def reject(self):
        if self.job and self.job.isRunning():
            self.status.setText('Please wait for the current operation to finish. A historical rescan can take a long time; Node Status shows its progress.'); return
        super().reject()

    def closeEvent(self, event):
        if self.job and self.job.isRunning(): event.ignore(); self.reject()
        else: event.accept()

    def wallet_selector(self):
        box = QComboBox(); box.setAccessibleName('Watch-only wallet')
        # Inventory is refreshed in a worker after the dialog is displayed.
        self.layout.addWidget(box); return box

    def load_wallet_names(self, box, done=None):
        def collect():
            names = []
            for name in self.service.rpc('listwallets'):
                try: self.service.watch(name); names.append(name)
                except WalletError: pass
            return names
        def loaded(names):
            box.clear(); box.addItems(names)
            self.status.setText('Please open Bitcoin Core and choose File → Restore Wallet to add your Vault watch-only export.' if not names else 'Watch-only wallets cannot sign transactions.')
            if done: done()
        self.run(collect, loaded)


class WalletDialog(WorkDialog):
    def __init__(self, parent):
        super().__init__(parent, 'Watch-Only Wallets')
        self.wallet = self.wallet_selector()
        row = QHBoxLayout(); self.layout.addLayout(row)
        self.button('Refresh wallet', self.refresh, row)
        self.details = self.text('Wallet balances, transactions and outputs')
        receive = QHBoxLayout(); self.layout.addLayout(receive)
        self.label = QLineEdit(); self.label.setPlaceholderText('Receiving address label'); self.label.setAccessibleName('Receiving address label'); receive.addWidget(self.label)
        self.kind = QComboBox()
        for kind in ('bech32', 'bech32m', 'p2sh-segwit', 'legacy'): self.kind.addItem(kind)
        receive.addWidget(self.kind)
        self.button('New receiving address', self.receive, receive)
        self.address = QLineEdit(); self.address.setReadOnly(True); self.address.setAccessibleName('New receiving address'); self.layout.addWidget(self.address)
        self.button('Close', self.reject)
        self.wallet.currentTextChanged.connect(lambda _: self.refresh())
        def initial_wallets():
            self.load_wallet_names(self.wallet)
            self.job.finished.connect(lambda: QTimer.singleShot(0, self.refresh))
        QTimer.singleShot(0, initial_wallets)

    def refresh(self):
        name = self.wallet.currentText()
        if not name: return
        def done(data):
            self.status.setText('Balance is provisional: synchronization or the wallet rescan is incomplete.' if data['incomplete'] else 'Watch-only wallet • blockchain and wallet scan are current.')
            balance = data['balances'].get('mine', data['balances'].get('watchonly', {}))
            lines = ['Wallet: '+name, 'Private keys: disabled',
                     'Confirmed: '+amount(balance.get('trusted', 0))+' BTC',
                     'Unconfirmed: '+amount(balance.get('untrusted_pending', 0))+' BTC',
                     'Immature: '+amount(balance.get('immature', 0))+' BTC',
                     'Rescan: '+str(data['info'].get('scanning')), '', 'UNSPENT OUTPUTS']
            for coin in data['utxos']:
                lines += [amount(coin['amount'])+' BTC • '+str(coin['confirmations'])+' confirmations', coin['txid']+':'+str(coin['vout'])]
            lines += ['', 'RECENT TRANSACTIONS']
            for tx in data['transactions']:
                lines += [tx.get('category', '')+'  '+str(tx.get('amount', ''))+' BTC • '+str(tx.get('confirmations', 0))+' confirmations',
                          tx.get('label', '')+'  '+tx.get('address', ''), tx['txid'], '']
            self.details.setPlainText('\n'.join(lines))
        self.run(lambda: self.service.snapshot(name), done)

    def receive(self):
        name, label, kind = self.wallet.currentText(), self.label.text(), self.kind.currentText()
        if name: self.run(lambda: self.service.receive(name, label, kind), lambda value: (self.address.setText(value), self.status.setText('Address created. For high-value receipts, independently verify it against offline Vault.')))
