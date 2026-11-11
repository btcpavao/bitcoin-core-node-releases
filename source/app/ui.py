"""Persistent Node management UI. Closing it never owns or stops bitcoind."""
import json
from pathlib import Path
import subprocess
import fcntl
import os
import shutil
from PySide6.QtCore import Qt, QSize, QThread, QTimer, Signal, Slot, QEvent
from PySide6.QtGui import QColor, QIcon, QPalette, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
    QFileDialog, QFormLayout, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QStyle, QTextBrowser, QVBoxLayout, QWidget)
from rpc import CoreRPC
from wallet_presence import watch_only_wallets_present
from state import load_setup
from launcher_ui import ToolCard, themed_icon, StatusLabel
from desktop_surface import DesktopSurface, HintButton, STYLE as DESKTOP_STYLE
from activity_ui import ActivityIndicator, StorageBar, node_activity

STYLE='''
QWidget { background:#0b0b0b; color:#f2f2f2; font-size:14px; }
QLabel#Title { font-size:30px; font-weight:700; }
QLabel#Muted { color:#b5b5b5; }
QPushButton#ToolCard { background:#151515; border:1px solid #333; border-radius:10px; padding:0; }
QPushButton#ToolCard:hover { background:#202020; border-color:#555; }
QPushButton#ToolCard:focus { border:2px solid #f7931a; }
QPushButton#ToolCard QLabel { background:transparent; border:none; }
QLabel#CardTitle { font-size:14px; font-weight:600; }
QLabel#CardDescription { font-size:11px; color:#b5b5b5; }
QScrollArea#LauncherScroll { border:none; background:transparent; }
QPushButton#Power { background:transparent; border:1px solid transparent; border-radius:24px; padding:0; }
QPushButton#Power:hover { background:#202020; }
QPushButton#Power:focus { border-color:#f7931a; }
QPushButton { background:#181818; border:1px solid #555; border-radius:8px; padding:14px; }
QPushButton:hover { background:#282828; }
QPushButton:focus, QLineEdit:focus, QComboBox:focus { border:2px solid #f7931a; }
QLineEdit, QComboBox, QSpinBox, QPlainTextEdit { background:#151515; border:1px solid #666; padding:8px; }
QComboBox { combobox-popup:0; selection-background-color:#343434; selection-color:#fff; }
QComboBox QAbstractItemView {
    background:#121212; color:#fff; border:1px solid #4a4a4a;
    border-radius:0px; padding:4px; outline:0;
    selection-background-color:#343434; selection-color:#fff;
}
QComboBox QAbstractItemView::item:selected { background:#343434; color:#fff; }
QComboBoxPrivateContainer { background:#121212; border:1px solid #4a4a4a; padding:0px; }
QComboBox QAbstractItemView::item { min-height:28px; padding:4px 8px; }
QCheckBox { spacing:8px; }
QCheckBox::indicator, QAbstractItemView::indicator { width:18px; height:18px; border:2px solid #888; border-radius:3px; background:#151515; }
QCheckBox::indicator:checked, QAbstractItemView::indicator:checked { background:#f7931a; border-color:#f2f2f2; }
QCheckBox::indicator:disabled, QAbstractItemView::indicator:disabled { border-color:#555; }
QCheckBox:focus { outline:1px solid #f7931a; }
'''


def configure_ui(app):
    app.setStyle('Fusion')
    QIcon.setThemeSearchPaths(['/usr/share/icons',':/icons'])
    QIcon.setThemeName('Adwaita');QIcon.setFallbackThemeName('hicolor')
    palette=QPalette()
    for role,color in [('Window','#0b0b0b'),('WindowText','#f2f2f2'),('Base','#151515'),
                       ('AlternateBase','#181818'),('Text','#f2f2f2'),('Button','#181818'),
                       ('ButtonText','#f2f2f2'),('ToolTipBase','#181818'),('ToolTipText','#f2f2f2'),
                       ('Highlight','#f7931a'),('HighlightedText','#0b0b0b'),('PlaceholderText','#888888'),
                       ('Light','#555555'),('Mid','#444444'),('Dark','#111111'),('Shadow','#000000')]:
        palette.setColor(getattr(QPalette,role),QColor(color))
    for role in [QPalette.Text,QPalette.WindowText,QPalette.ButtonText]:
        palette.setColor(QPalette.Disabled,role,QColor('#777777'))
    app.setPalette(palette)


class Job(QThread):
    success=Signal(object)
    failure=Signal(str)
    def __init__(self,fn,parent):super().__init__(parent);self.fn=fn
    def run(self):
        try:self.success.emit(self.fn())
        except Exception as exc:
            from wallets import WalletError
            from rpc import CoreError
            from state import SetupError
            from system_time import TimeError
            safe=isinstance(exc,(WalletError,CoreError,SetupError,TimeError))
            self.failure.emit(str(exc) if safe else 'The operation could not be completed. Please check Node status, the selected file and local diagnostics.')
        finally:self.fn=None


def admin(action,request=None):
    # Power has its own bounded authorization. Enabling a login password must
    # not turn a normal local restart into a general administration prompt.
    if action in ('reboot','poweroff'):
        helper='/usr/libexec/core-node-power'
    elif action in ('start','stop','restart'):
        helper='/usr/libexec/core-node-service'
    else:
        helper='/usr/libexec/core-node-admin'
    result=subprocess.run(['/usr/bin/pkexec',helper,action],
        input='' if request is None else json.dumps(request),capture_output=True,text=True,
        timeout=4000 if action in ('debian-updates','core-update') else 400)
    if result.returncode:
        from wallets import WalletError
        raise WalletError(result.stderr.strip()[:800] or 'Administration did not complete.')
    response = json.loads(result.stdout)
    if response.get('ok') and action in ('configure', 'start', 'restart', 'time-settings',
            'core-update', 'software-install', 'debian-updates', 'settings-import',
            'core-settings-import', 'watch-import', 'wallet-delete', 'keyboard-settings'):
        from home_backup import remember_local_use
        remember_local_use()
    return response


class PrivacyDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setWindowTitle('Network & Privacy');self.resize(720,650)
        self.setStyleSheet(STYLE);self.request=None
        try:old=load_setup()
        except Exception:old=None
        self.old=old
        layout=QVBoxLayout(self)
        heading=QLabel('Choose your network privacy');heading.setObjectName('Title');layout.addWidget(heading)
        self.profile=QComboBox()
        for text,value in [('Clearnet — Default','clearnet'),('Tor — Private Bitcoin P2P','tor'),('VPN — WireGuard','wireguard')]:self.profile.addItem(text,value)
        self.profile.setCurrentIndex(self.profile.findData(old['profile']) if old else 0)
        layout.addWidget(self.profile)
        self.explanation=QLabel();self.explanation.setWordWrap(True);layout.addWidget(self.explanation)
        self.wg=QPlainTextEdit();self.wg.setAccessibleName('WireGuard configuration')
        self.wg.setPlaceholderText('Import your provider or self-hosted WireGuard configuration. Private keys stay in the protected local configuration.')
        self.wg.setMaximumHeight(150)
        self.import_wg=QPushButton('Import WireGuard configuration…')
        self.import_wg.clicked.connect(self.read_wg)
        layout.addWidget(self.import_wg);layout.addWidget(self.wg)
        self.private=QCheckBox('Use private transaction broadcast through Tor')
        self.private.setChecked(old['private_broadcast'] if old else False);layout.addWidget(self.private)
        broadcast=QLabel('Private broadcast uses Core’s separate sendrawtransaction route without standard fallback. Enabling it also makes Tor available for ordinary peers. Tor availability does not promise anonymity.')
        broadcast.setWordWrap(True);layout.addWidget(broadcast)
        note=QLabel('Choose block storage and pruning in Bitcoin Core → Settings → Options.')
        note.setWordWrap(True);layout.addWidget(note)
        buttons=QHBoxLayout();cancel=QPushButton('Back to Settings');confirm=QPushButton('Apply network settings')
        cancel.clicked.connect(self.reject);confirm.clicked.connect(self.confirm)
        buttons.addWidget(cancel);buttons.addWidget(confirm);layout.addLayout(buttons)
        self.profile.currentIndexChanged.connect(self.describe);self.describe()

    def describe(self):
        mode=self.profile.currentData()
        texts={'clearnet':'Bitcoin connects directly over IPv4/IPv6. Peers see your public IP and your ISP may identify Bitcoin traffic.',
        'tor':'Bitcoin P2P uses Tor and stops connecting if Tor fails. Debian updates and other operating-system traffic still use the normal network.',
        'wireguard':'Whole-device traffic uses the VPN tunnel. A kill switch blocks fallback, DNS and IPv6 outside the tunnel, apart from the configured VPN endpoint and essential link setup. Your VPN operator becomes a trust point.'}
        self.explanation.setText(texts[mode]);self.wg.setVisible(mode=='wireguard');self.import_wg.setVisible(mode=='wireguard')

    def read_wg(self):
        from media_file_dialog import choose_media_file
        filename=choose_media_file(self,'Import WireGuard configuration','/media',name_filter='WireGuard (*.conf)')
        if filename:
            try:
                with open(filename,'rb') as stream:data=stream.read(16385)
                if len(data)>16384:raise ValueError()
                self.wg.setPlainText(data.decode())
            except Exception:QMessageBox.warning(self,'Import failed','Please choose a valid configuration of at most 16 KiB.')

    def confirm(self):
        from state import validate_setup
        from network import wireguard
        setup={'version':1,'confirmed':True,'profile':self.profile.currentData(),
               'network':self.old['network'] if self.old else 'main',
               'prune_mib':self.old['prune_mib'] if self.old else 0,
               'data_uuid':self.old['data_uuid'] if self.old else None,'private_broadcast':self.private.isChecked()}
        try:
            validate_setup(setup)
            if setup['profile']=='wireguard':wireguard(self.wg.toPlainText())
        except Exception as exc:
            QMessageBox.warning(self,'Please check the settings',str(exc));return
        changed=self.old and self.old['prune_mib']!=setup['prune_mib']
        if changed and QMessageBox.question(self,'Change retained block history?',
                'Enabling or reducing pruning may permanently remove downloaded block files. Disabling it may require a full blockchain download and reindex. Please confirm this change.',
                QMessageBox.Yes|QMessageBox.Cancel,QMessageBox.Cancel)!=QMessageBox.Yes:return
        self.request={'setup':setup,'confirm_prune':bool(changed)}
        if setup['profile']=='wireguard':self.request['wireguard']=self.wg.toPlainText()
        self.accept()


def branding_file(name):
    installed=Path('/usr/share/bitcoin-core-node')/name
    return installed if installed.exists() else Path(__file__).resolve().parents[1]/'runtime/usr/share/bitcoin-core-node'/name


STYLE += '\nQCheckBox::indicator:checked { background:#151515; border-color:#55d68b; image:url(' + str(branding_file('icons/check-green.svg')) + '); }\n'


class Home(DesktopSurface):
    def __init__(self):
        self.rpc=CoreRPC();self.job=None;self.crypto_process=None;self.power_flow_open=False
        actions=[('Bitcoin Core','Open Bitcoin Core',(),QStyle.SP_ComputerIcon,self.open_core),
                 ('Watch-Only Wallets','Balances, addresses & history',(),QStyle.SP_ComputerIcon,lambda:self.wallet_action('WalletDialog')),
                 ('PSBT Transfer Folder','Temporary PSBT exchange in RAM',('folder-publicshare','folder'),QStyle.SP_DirIcon,self.psbt_workspace),
                 ('Private Workspace','Temporary files in RAM',('folder-locked','folder'),QStyle.SP_DirIcon,self.private_workspace),
                 ('Backup and Restore','Blockchain, wallets & settings',(str(branding_file('icons/settings-chain-backup.png')),),QStyle.SP_DialogSaveButton,self.backup_restore),
                 ('Encrypt Files','Create verified GPG files',('document-encrypt','changes-prevent'),QStyle.SP_DialogSaveButton,lambda:self.file_crypto('create')),
                 ('Decrypt Files','Recover files into RAM',(str(branding_file('icons/decrypt-files.png')),'document-decrypt','changes-allow'),QStyle.SP_DialogOpenButton,lambda:self.file_crypto('decrypt')),
                 ('KeePassXC','Generate random passphrases',('keepassxc',),QStyle.SP_FileDialogDetailedView,self.keepass),
                 ('Settings','Network, devices & updates',('preferences-system','preferences-other'),QStyle.SP_FileDialogDetailedView,self.settings),
                 ('Files','Core, workspace and USB',('org.xfce.thunar','system-file-manager','folder'),QStyle.SP_DirIcon,self.files),
                 ('Editor','Notes and instructions',('org.xfce.mousepad','accessories-text-editor'),QStyle.SP_FileIcon,lambda:subprocess.Popen(['/usr/bin/mousepad'])),
                 ('Terminal','Advanced tools',('org.xfce.terminal','utilities-terminal'),QStyle.SP_ComputerIcon,lambda:subprocess.Popen(['/usr/bin/xfce4-terminal'])),
                 ('Node Guide','Node workflows & help',('help-browser','help-contents'),QStyle.SP_MessageBoxInformation,self.guide)]
        card_help={
            'Bitcoin Core': 'Start Bitcoin Core to download and independently validate the blockchain, or return to its window if it is already running.',
            'Watch-Only Wallets': 'Manage your imported public wallets: view receiving addresses, balances and transaction history.',
            'PSBT Transfer Folder': 'Exchange PSBTs with Bitcoin Core and an offline signer. Files stay in RAM and are lost on restart or shutdown; save needed copies to USB.',
            'Private Workspace': 'Open temporary files held in RAM. Everything in this folder is lost when you restart or shut down.',
            'Backup and Restore': 'Back up or restore blockchain data, watch-only wallets and configuration. This shortcut appears after Node use; it is not a backup-status indicator.',
            'Encrypt Files': 'Encrypt selected files with GPG, verify recovery, then save the encrypted copy to USB or disk. For wallets, first use Bitcoin Core File → Backup Wallet.',
            'Decrypt Files': 'Authenticate and decrypt GPG files into Private Workspace. Decrypted files stay in RAM until you explicitly copy them elsewhere.',
            'KeePassXC': 'Open the passphrase generator with six random EFF words, as on Vault. Change the length as needed. Its temporary profile stays in RAM; save any database you need to keep to USB or disk.',
            'Settings': 'Configure date and time, Bluetooth devices, mouse speed, Bitcoin Core privacy and status, login password and software updates.',
            'Files': 'Open Core data for inspection, or use the sidebar to reach Private Workspace and USB drives. Use Bitcoin Core for wallet backups and changes.',
            'Editor': 'Write and edit plain-text notes or instructions, then save them to persistent storage or a USB drive.',
            'Terminal': 'Open a command line for Bitcoin Core and system diagnostics, log inspection and advanced administration.',
            'Node Guide': 'Read illustrated instructions for synchronization, networking, watch-only wallets, PSBT transfers, backups and maintenance.',
        }
        self.actions={label:action for label,description,names,fallback,action in actions}
        tools=[dict(title=label,description=description,help=card_help[label],icons=names,
                    fallback=fallback,command=None) for label,description,names,fallback,action in actions]
        super().__init__(tools,branding_file('bitcoin-ui.png').parent,'Bitcoin Core Node',
                         'Bitcoin Core online node environment.')
        self.setStyleSheet(STYLE+DESKTOP_STYLE)
        self.all_home_cards = tuple(self.cards)
        self.wallet_manager_card = next(c for c in self.cards
                                        if c.tool['title'] == 'Watch-Only Wallets')
        self.wallet_manager_card.setParent(self.grid_wrap)
        self.psbt_card=next(c for c in self.cards if c.tool['title']=='PSBT Transfer Folder')
        self.psbt_card.setParent(self.grid_wrap)
        from home_backup import BackupPresence
        self.backup_presence = BackupPresence()
        self.backup_card = next(c for c in self.cards if c.tool['title'] == 'Backup and Restore')
        self.backup_card.setParent(self.grid_wrap)
        self.backup_available = self.backup_presence.remembered()
        self.watch_only_available = None
        self.set_watch_only_available(False)
        self.wallet_inventory_rpc = CoreRPC(timeout=2)
        self.wallet_inventory_job = None
        self.wallet_inventory_pending = False
        self.wallet_inventory_timer = QTimer(self)
        self.wallet_inventory_timer.setInterval(5000)
        self.wallet_inventory_timer.timeout.connect(self.poll_wallets)
        self.wallet_inventory_timer.start()
        QTimer.singleShot(0, lambda: self.poll_wallets()
                          if self.wallet_inventory_timer.isActive() else None)
        # Keep node health separate from operation feedback so polling cannot hide errors.
        self.activity=ActivityIndicator(self)
        self.activity_text=QLabel('Checking Bitcoin Core status…')
        self.activity_text.setWordWrap(True);self.activity_text.setAlignment(Qt.AlignCenter)
        self.activity_text.setTextFormat(Qt.PlainText)
        self.activity_text.setAccessibleName('Bitcoin Core status')
        self.activity_text.setStyleSheet('font-style:italic;')
        self.activity_seen=False
        self.activity_row=QWidget();self.activity_row.setStyleSheet('background:transparent;')
        # A fresh desktop stays quiet until Core starts or reports a fault.
        # Reserve the same space so revealing activity does not move the cards.
        activity_policy=self.activity_row.sizePolicy()
        activity_policy.setRetainSizeWhenHidden(True)
        self.activity_row.setSizePolicy(activity_policy)
        self.activity_row.hide()
        activity_layout=QVBoxLayout(self.activity_row)
        activity_layout.setContentsMargins(12,0,12,0);activity_layout.setSpacing(3)
        # Keep labels above their meters. No spinning indicator or fake motion.
        activity_layout.addWidget(self.activity_text)
        activity_layout.addWidget(self.activity,alignment=Qt.AlignHCenter)
        self.activity.setVisible(False)
        self.blockchain_storage=StorageBar(self)
        self.blockchain_storage.setVisible(False)
        activity_layout.addWidget(self.blockchain_storage,alignment=Qt.AlignHCenter)
        # Keep the whole activity stack between the application cards and footer.
        index=self.body_layout.indexOf(self.grid_wrap)+1
        self.activity_slot=QWidget()
        self.activity_slot.setStyleSheet('background:transparent;')
        self.activity_slot.setFixedHeight(145)
        self.body_layout.insertWidget(index,self.activity_slot)
        self.activity_row.setParent(self)
        self.activity_row.setFixedWidth(620)
        # Position status independently of the card-layout cache. Its visible
        # height and the footer can change without a new card/text layout key.
        self.activity_position_timer=QTimer(self)
        self.activity_position_timer.setSingleShot(True)
        self.activity_position_timer.timeout.connect(self.position_activity)
        self.geometry_timer.timeout.connect(self.queue_activity_position)
        self.status=StatusLabel('');self.status.setWordWrap(True);self.status.setTextFormat(Qt.PlainText)
        self.status.setAlignment(Qt.AlignCenter);self.status.setContentsMargins(12,0,12,16)
        self.body_layout.insertWidget(self.body_layout.indexOf(self.activity_slot)+1,self.status)
        from time_ui import ClockButton
        self.clock=ClockButton(self)
        self.activity_job=None
        self.timer=QTimer(self);self.timer.setInterval(5000)
        self.timer.timeout.connect(self.poll_activity);self.timer.start()
        QTimer.singleShot(0,lambda:self.poll_activity() if self.timer.isActive() else None)
        network_help='Network Status: choose an available Wi-Fi network, connect, or open advanced settings.'
        self.network_button=HintButton('',network_help,self.show_card_help,self.hide_card_help)
        self.network_button.setObjectName('NetworkStatus')
        self.network_button.setAccessibleName('Network Status')
        self.network_button.setAccessibleDescription(network_help)
        self.network_button.setIcon(QIcon(str(branding_file('icons/network-status.png'))))
        self.network_button.setIconSize(QSize(44,44));self.network_button.setFixedSize(48,48)
        self.network_button.clicked.connect(self.network_status)
        controls=self.power_icon_row.layout()
        controls.insertWidget(controls.indexOf(self.restart_button),self.network_button)
        from connection_ui import ConnectionButton
        self.connection_button=ConnectionButton(self)
        self.info_box=self.footer.findChild(QWidget,'FooterSpacer')
        # Three levels in one right-hand stack:
        # 1. Bitcoin Core peer status, 2. date/time, 3. network/restart/shutdown.
        # All are independent clickable controls; the left footer remains empty.
        self.power_info_layout.addWidget(self.connection_button,0,Qt.AlignHCenter)
        self.power_info_layout.addWidget(self.clock,0,Qt.AlignHCenter)
        self.layout_footer()

    def layout_footer(self):
        if not all(hasattr(self,name) for name in ('clock','network_button','connection_button')):return
        width=self._test_size[0] if self._test_size else self.screen_ref.geometry().width()
        self.clock.compact=False
        self.connection_button.set_compact(width<1100)
        self.clock.refresh()
        self.clock.ensurePolished()
        # Icon, icon/text spacing, borders and Qt's button padding all consume
        # width. The old text_width+26 clipped the final clock digit on T550.
        text_width=max(self.clock.fontMetrics().horizontalAdvance(line)
                       for line in self.clock.text().splitlines())
        button_width=max(218,self.clock.sizeHint().width()+12,
                         text_width+self.clock.iconSize().width()+48)
        zone=max(248,self.connection_button.width()+16,button_width+12)
        # Equal-width footer zones keep Powered by Debian exactly centered,
        # independently of minute changes and display font scaling.
        key=(width,text_width,self.clock.fontMetrics().height(),
             self.credit_box.minimumSizeHint().width(),
             self.outer.contentsMargins().left(),self.outer.contentsMargins().right(),zone)
        if getattr(self,'_footer_key',None)==key:return
        self._footer_key=key
        self.clock.setFixedSize(button_width,26)
        self.power_box.setFixedWidth(zone)
        self.info_box.setFixedWidth(zone)
        self.outer.invalidate()

    def fit_screen(self):
        # Release the wide footer's minimum before requesting a narrower window.
        # Otherwise X11 can keep the old width even after the clock wraps.
        self.layout_footer()
        if hasattr(self,'clock'):self.outer.activate()
        super().fit_screen()

    def layout_cards(self):
        self.layout_footer()
        # The progress meter must span enough width for 100 clearly visible
        # segments while still fitting the T550's compact desktop.
        if hasattr(self,'activity') and hasattr(self,'blockchain_storage'):
            screen_width=self._test_size[0] if self._test_size else self.screen_ref.geometry().width()
            width=min(620,max(300,screen_width-180))
            if self.activity.width()!=width:self.activity.setFixedWidth(width)
            if self.blockchain_storage.width()!=width:self.blockchain_storage.setFixedWidth(width)
        super().layout_cards()
        self.queue_activity_position()

    def backup_restore(self):
        from backup_restore_ui import BackupRestoreDialog
        from modeless import open_window
        return open_window(self,"backup_restore",lambda:BackupRestoreDialog(self))

    def settings_snapshot(self):
        from settings_snapshot_ui import SettingsSnapshotDialog
        from modeless import open_window
        return open_window(self,"settings_snapshot",lambda:SettingsSnapshotDialog(self))

    def chain_backup(self):
        from chain_ui import ChainDialog
        from modeless import open_window
        return open_window(self,"chain_backup",lambda:ChainDialog('backup',self))

    def chain_import(self):
        from chain_ui import ChainDialog
        from modeless import open_window
        return open_window(self,"chain_import",lambda:ChainDialog('import',self))

    def reflow_optional_cards(self):
        self.hide_card_help()
        optional = {self.wallet_manager_card: bool(self.watch_only_available),
                    self.psbt_card: bool(self.watch_only_available),
                    self.backup_card: bool(self.backup_available)}
        for card, visible in optional.items():
            self.grid.removeWidget(card); card.setVisible(visible)
        self.cards = [c for c in self.all_home_cards if optional.get(c, True)]
        self._layout_key = None
        self.layout_cards()

    def set_backup_available(self, available):
        # One-way discovery: stopping Core or making a backup does not remove it.
        if available and not self.backup_available:
            self.backup_available = True
            self.backup_presence.remember()
            self.reflow_optional_cards()

    def set_watch_only_available(self, available):
        if available is None or available == self.watch_only_available:
            return
        self.watch_only_available = available
        if available:
            self.backup_available = True
            self.backup_presence.remember()
        self.reflow_optional_cards()

    def home_activity(self):
        # Existing worker, not UI-thread NM polling or another privileged daemon.
        value = node_activity()
        visible = self.backup_presence.check()
        return value, visible

    @Slot(object)
    def home_activity_received(self, value):
        activity, visible = value
        self.show_activity(activity)
        self.set_backup_available(visible)

    def poll_wallets(self):
        if self.wallet_inventory_job is not None:
            self.wallet_inventory_pending = True
            return
        self.wallet_inventory_pending = False
        job = Job(lambda: watch_only_wallets_present(self.wallet_inventory_rpc), self)
        self.wallet_inventory_job = job
        job.success.connect(self.wallet_inventory_received)
        # An unavailable Core is not evidence that an existing wallet was deleted.
        job.failure.connect(self.wallet_inventory_failed)
        job.finished.connect(self.wallet_inventory_finished)
        job.start()

    @Slot(object)
    def wallet_inventory_received(self, value):
        if not self.wallet_inventory_pending:
            self.set_watch_only_available(value)

    @Slot(str)
    def wallet_inventory_failed(self, _message):
        pass  # Unavailable RPC does not remove an existing wallet card.

    @Slot()
    def wallet_inventory_finished(self):
        job = self.sender()
        if self.wallet_inventory_job is job:
            self.wallet_inventory_job = None
        job.deleteLater()
        if self.wallet_inventory_pending:
            QTimer.singleShot(0, self.poll_wallets)

    def poll_activity(self):
        if self.activity_job is not None:return
        self.activity_job=Job(self.home_activity,self)
        self.activity_job.success.connect(self.home_activity_received)
        self.activity_job.failure.connect(self.activity_failed)
        self.activity_job.finished.connect(self.activity_finished)
        self.activity_job.start()

    @Slot(str)
    def activity_failed(self, _message):
        self.show_activity(('error','Node status unavailable. Please check Bitcoin Core and local service diagnostics.',False))

    @Slot()
    def activity_finished(self):
        # Clear the live reference in the GUI thread before scheduling deletion.
        # A finished-signal lambda can disappear with its deleted sender.
        job = self.sender()
        if self.activity_job is job:
            self.activity_job = None
        job.deleteLater()

    @Slot(object)
    def show_activity(self,value):
        state,text,animate=value[:3]
        if state in ('starting', 'syncing', 'synchronized'):
            self.set_backup_available(True)
        progress=value[3] if len(value)>3 else None
        disk=value[4] if len(value)>4 else None
        if state!='stopped':self.activity_seen=True
        self.activity.set_state(state,animate,progress)
        self.activity.setVisible(progress is not None and state in
                                 ('syncing','synchronized','starting'))
        self.blockchain_storage.update_space(disk if state in
                                              ('syncing','synchronized','starting') else None)
        self.activity_text.setText(text)
        self.activity_row.setVisible(self.activity_seen)
        self.activity_row.layout().invalidate()
        self.schedule_layout()
        self.queue_activity_position()

    def queue_activity_position(self):
        timer=getattr(self,'activity_position_timer',None)
        if timer is not None and not timer.isActive():timer.start(0)

    def eventFilter(self,watched,event):
        # The taskbar/work area and footer can settle after the grid's geometry
        # pass. React to their final bounds, including when the message itself
        # has not changed. Coalesce events; never keep polling the UI geometry.
        boundaries=('body','grid_wrap','footer','credit_box','debian_logo')
        content=('activity_row','activity_text','activity','blockchain_storage')
        kind=event.type()
        if ((kind in (QEvent.Move,QEvent.Resize,QEvent.Show,QEvent.Hide,QEvent.LayoutRequest)
                and any(watched is getattr(self,name,None) for name in boundaries))
            or (kind in (QEvent.LayoutRequest,QEvent.Show,QEvent.Hide,QEvent.FontChange,QEvent.StyleChange)
                and any(watched is getattr(self,name,None) for name in content))):
            self.queue_activity_position()
        return super().eventFilter(watched,event)

    def position_activity(self):
        """Center the visible text/meters between the last launcher and Debian."""
        if not hasattr(self,'activity_slot') or not hasattr(self,'debian_logo'):return
        from PySide6.QtCore import QPoint
        self.body_layout.activate()
        self.grid.activate()
        self.footer.layout().activate()
        self.credit_box.layout().activate()
        width=min(620,max(300,self.width()-60))
        self.activity_row.setFixedWidth(width)
        layout=self.activity_row.layout()
        height=layout.totalHeightForWidth(width)
        height=max(layout.minimumSize().height(),height if height>=0 else layout.sizeHint().height())
        # Shrink immediately when bars disappear; do not retain the former
        # multi-bar height when displaying stopped/error/starting text alone.
        self.activity_row.setFixedHeight(height)
        bottoms=[card.mapTo(self,QPoint(0,card.height())).y()
                 for card in self.cards if not card.isHidden()]
        if not bottoms:return
        top=max(bottoms)
        bottom=self.debian_logo.mapTo(self,QPoint(0,0)).y()
        y=round((top+bottom-height)/2)
        self.activity_row.setGeometry((self.width()-width)//2,y,width,height)
        layout.activate()
        self.activity_row.raise_()

    def mouse_settings(self):
        self.hide_card_help()
        from input_ui import KeyboardMouseDialog
        dialog=KeyboardMouseDialog(self)
        try:dialog.exec()
        finally:dialog.deleteLater()

    def bluetooth_devices(self, *, from_settings=False):
        self.hide_card_help()
        if from_settings:
            from bluetooth_ui import BluetoothDevicesDialog
            dialog=BluetoothDevicesDialog(self)
            try:dialog.exec()
            finally:dialog.deleteLater()
            return
        try:
            subprocess.Popen(['/usr/bin/blueman-manager'])
        except OSError:
            self.status.setText('Bluetooth Manager could not open. Please check the installed Bluetooth packages.')

    def network_status(self, *, from_settings=False):
        self.hide_card_help()
        from network_ui import NetworkDialog
        if from_settings:
            # Network is a navigable Settings child; the Home shortcut keeps
            # its original nonmodal, minimizable chooser behavior.
            dialog=NetworkDialog(self,for_settings=True)
            try:dialog.exec()
            finally:dialog.deleteLater()
            return
        dialog=getattr(self,'network_dialog',None)
        if dialog is None:
            dialog=NetworkDialog(self)
            self.network_dialog=dialog
            dialog.finished.connect(self.network_closed)
        # Network management must never make the desktop unclickable when
        # another native window takes focus or the chooser is minimized.
        if dialog.isMinimized():dialog.showNormal()
        else:dialog.show()
        dialog.raise_();dialog.activateWindow()

    @Slot(int)
    def network_closed(self,_result):
        dialog=self.network_dialog;self.network_dialog=None
        dialog.deleteLater()

    def activate_tool(self,title,command):
        self.hide_card_help()
        self.actions[title]()

    def restart(self):
        self.hide_card_help();self.power('reboot')

    def shutdown(self):
        self.hide_card_help();self.power('poweroff')

    def settings(self):
        from launcher_ui import NodeSettingsDialog
        from modeless import open_window
        self.settings_dialog=open_window(self,'settings',lambda:NodeSettingsDialog(self))
        return self.settings_dialog

    def date_time(self):
        self.hide_card_help()
        from time_ui import DateTimeDialog
        dialog=DateTimeDialog(self)
        try:dialog.exec()
        finally:dialog.deleteLater()

    def keepass(self):
        self.hide_card_help()
        from keepass_launcher import launch
        from private_workspace import WorkspaceError
        try:
            self.children_started.append(launch())
            self.status.setText('')
        except (OSError,WorkspaceError) as exc:
            self.status.setText(str(exc) if isinstance(exc,WorkspaceError)
                                else 'KeePassXC could not open. Please check the installed application.')

    def power(self,action):
        if action not in ('reboot','poweroff'):raise ValueError('Unsupported power action')
        if self.power_flow_open:return
        from system_updates import read_status
        if read_status().get('busy'):
            QMessageBox.information(self,'Software maintenance is running',
                'Please wait for software maintenance to finish before restarting or shutting down. Open Software Updates to follow its progress.');return
        if self.job and self.job.isRunning():
            QMessageBox.information(self,'Operation in progress','Please wait for the current operation to finish.');return
        if self.crypto_process is not None and self.crypto_process.poll() is None:
            QMessageBox.information(self,'Encryption tool is open','Please finish or cancel the file operation and close its window before restarting or shutting down.');return
        restart=action=='reboot'
        from power_ui import confirm_power_action
        self.power_flow_open=True
        try:
            if not confirm_power_action(restart,self):return
        finally:self.power_flow_open=False
        self.status.setText('Restarting the computer…' if restart else 'Shutting down the computer…')
        def request():
            # Complete Core's normal shutdown while X11 is still available.
            # The bounded helper refuses to power off if stopping Core fails.
            return admin(action)
        self.start(request,lambda _:None)

    def start(self,fn,success):
        if self.job and self.job.isRunning():return
        self.operation_callback=success;self.operation_value=None;self.operation_error=None
        self.operation_has_value=False
        self.job=Job(fn,self)
        self.job.success.connect(self.operation_received)
        self.job.failure.connect(self.operation_failed)
        self.job.finished.connect(self.operation_finished)
        self.job.start()

    @Slot(object)
    def operation_received(self,value):
        self.operation_value=value;self.operation_has_value=True

    @Slot(str)
    def operation_failed(self,text):
        self.operation_error=text

    @Slot()
    def operation_finished(self):
        job=self.sender()
        if self.job is not job:return
        callback,value,error,received=self.operation_callback,self.operation_value,self.operation_error,self.operation_has_value
        self.job=None;self.operation_callback=None;self.operation_value=None
        job.deleteLater()
        # Continuations can start Core or open another dialog immediately.
        # The preceding worker must already be detached before either happens.
        if error is not None:self.status.setText(error)
        elif received:callback(value)

    def refresh(self, *, from_settings=False):
        from core_status_ui import CoreStatusDialog
        from modeless import open_window
        return open_window(self,'core-status',lambda:CoreStatusDialog(self,from_settings=from_settings))

    def show_bitcoin_core_status(self,rows,*,from_settings=False):
        dialog=self.refresh(from_settings=from_settings)
        dialog.details.setPlainText('\n\n'.join(str(k)+': '+str(v) for k,v in rows))
        return dialog

    def login_settings(self):
        from login_ui import LoginDialog
        dialog=LoginDialog(self)
        try:dialog.exec()
        finally:dialog.deleteLater()

    def private_workspace(self):
        from private_workspace import check_storage, WorkspaceError
        try:
            folder=check_storage()
            subprocess.Popen(['/usr/bin/thunar',str(folder)])
        except (WorkspaceError,OSError) as exc:
            self.status.setText(str(exc) if isinstance(exc,WorkspaceError) else 'Files could not open.')

    def psbt_workspace(self):
        from private_workspace import check_psbt_storage,WorkspaceError
        try:subprocess.Popen(['/usr/bin/thunar',str(check_psbt_storage())])
        except (WorkspaceError,OSError) as exc:self.status.setText(str(exc))

    def files(self):
        from file_browser import open_core_files, BrowserError
        try:open_core_files()
        except (BrowserError,OSError) as exc:
            self.status.setText(str(exc) if isinstance(exc,BrowserError) else 'Files could not open.')

    def file_crypto(self,mode):
        if self.crypto_process is not None and self.crypto_process.poll() is None:
            self.status.setText('The file encryption tool is already open. Please finish or cancel that operation first.');return
        from private_workspace import check_storage, WorkspaceError
        try:
            check_storage()
            self.crypto_process=subprocess.Popen(['/usr/local/bin/core-node-files-crypto',mode],
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            self.status.setText('')
        except (WorkspaceError,OSError) as exc:
            self.status.setText(str(exc) if isinstance(exc,WorkspaceError) else 'The file encryption tool could not open.')

    def wallet_action(self,name):
        import wallet_ui
        dialog=getattr(wallet_ui,name)(self)
        dialog.exec()
        self.poll_wallets()

    def privacy(self):
        if self.job and self.job.isRunning():
            self.status.setText('Please wait for the current operation to finish, then open Network & Privacy.');return
        dialog=PrivacyDialog(self)
        if dialog.exec()==QDialog.Accepted:
            request=dialog.request;dialog.wg.clear();dialog.request=None
            self.status.setText('Applying the confirmed network profile…')
            self.start(lambda:admin('configure',request),lambda _:self.status.setText('Profile applied. Refresh status to see synchronization.'))

    def open_core(self):
        if self.job and self.job.isRunning():
            self.status.setText('Please wait for the current operation to finish.');return
        from network_access import snapshot, NetworkError
        def check():
            try: return snapshot(scan=False)
            except NetworkError: return {'connected':False}
        def checked(data):
            self.offer_network(data)
        self.start(check,checked)

    def offer_network(self,data):
        if not data['connected']:
            from network_ui import NetworkDialog
            if NetworkDialog(self,for_core=True).exec()!=QDialog.Accepted:
                return
        self.control('start')

    def control(self,action):
        if self.job and self.job.isRunning():
            self.status.setText('Please wait for the current operation to finish.');return
        def request():
            if action in ('start','restart'):
                # Grant only the fixed unprivileged Core account access to this X
                # session; never launch the GUI as root or accept arbitrary env.
                subprocess.run(['/usr/bin/xhost','+SI:localuser:bitcoinnode'],
                               check=True,capture_output=True,timeout=10)
            return admin(action)
        def done(_):
            self.status.setText('')
            self.poll_activity()
            if action in ('start','restart'):
                subprocess.run(['/usr/bin/wmctrl','-xa','bitcoin-qt'],
                               capture_output=True,timeout=5)
        self.start(request,done)

    def updates(self):
        from software_ui import SoftwareUpdatesDialog
        dialog=SoftwareUpdatesDialog(self)
        try:dialog.exec()
        finally:dialog.deleteLater()

    def guide(self):
        from guide_ui import Guide
        dialog=Guide(self);dialog.exec()

    def closeEvent(self,event):
        event.ignore()  # Match the Vault desktop surface; applications close independently.


def main():
    directory=Path.home()/'.local/state/bitcoin-core-node'
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    descriptor=os.open(directory/'ui.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:fcntl.flock(descriptor,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(descriptor);return
    try:
        app=QApplication([]);configure_ui(app)
        home=Home();home.show();app.exec()
    finally:os.close(descriptor)
