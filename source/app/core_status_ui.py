"""Live local-RPC status dashboard; no invented progress or remote telemetry."""
import json,shutil,subprocess,time
from PySide6.QtCore import Qt,QThread,QTimer,Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QDialog,QFrame,QGridLayout,QHBoxLayout,QLabel,
    QPlainTextEdit,QProgressBar,QPushButton,QVBoxLayout)
from rpc import CoreRPC
from state import load_setup
from desktop_surface import optical_icon


def snapshot():
    rpc=CoreRPC(timeout=2)
    try:
        chain=rpc('getblockchaininfo');net=rpc('getnetworkinfo')
    except Exception:
        try:service=subprocess.run(['/usr/bin/systemctl','is-active','bitcoin-core-node.service'],capture_output=True,text=True,timeout=3).stdout.strip()
        except Exception:service='unknown'
        return dict(available=False,service=service,updated=time.time())
    try:mempool=rpc('getmempoolinfo')
    except Exception:mempool={}
    try:peers=rpc('getpeerinfo')
    except Exception:peers=[]
    try:setup=load_setup() or {}
    except Exception:setup={}
    try:free=shutil.disk_usage('/var/lib/bitcoin-core-node/data').free
    except OSError:free=None
    scans={}
    try:
        names=rpc('listwallets')
        for name in names[:32]:
            try:scans[name]=rpc('getwalletinfo',wallet=name).get('scanning')
            except Exception:scans[name]='unavailable'
        if len(names)>32:scans['additional_wallets_not_polled']=len(names)-32
    except Exception:pass
    try:service=subprocess.run(['/usr/bin/systemctl','is-active','bitcoin-core-node.service'],capture_output=True,text=True,timeout=3).stdout.strip()
    except Exception:service='unknown'
    transport={};protocols={}
    for peer in peers:
        kind=str(peer.get('network','unknown'));transport[kind]=transport.get(kind,0)+1
        protocol=kind+' / '+str(peer.get('transport_protocol_type','unknown'));protocols[protocol]=protocols.get(protocol,0)+1
    return dict(available=True,chain=chain,net=net,mempool=mempool,privacy=setup.get('profile','Unknown'),free=free,
                transports=transport,transport_protocols=protocols,wallet_rescans=scans,service=service,presync=max((p.get('presynced_headers',-1) for p in peers),default=-1),updated=time.time())


class Worker(QThread):
    received=Signal(object)
    def run(self):
        try:self.received.emit(snapshot())
        except Exception:self.received.emit(dict(available=False,service='unknown',updated=time.time()))


class CoreStatusDialog(QDialog):
    def __init__(self,owner=None,*,from_settings=True,autostart=True):
        super().__init__(owner)
        from ui import STYLE,branding_file
        self.navigation_owner=owner;self.from_settings=from_settings;self.job=None;self.closing=False;self.validating=False;self.tick_count=0;self.latest={}
        self.setWindowTitle('Bitcoin Core Status');self.resize(760,590)
        self.setStyleSheet(STYLE+'''
QFrame#Metric {background:#151515;border:1px solid #3f3f3f;border-radius:10px;}
QFrame#Metric QLabel {background:transparent;border:none;}
QLabel#Value {font-size:23px;font-weight:600;}
QProgressBar {border:1px solid #444;border-radius:6px;min-height:24px;text-align:center;background:#151515;}
QProgressBar::chunk {background:#3a774e;border-radius:5px;}
''')
        layout=QVBoxLayout(self);layout.setContentsMargins(22,18,22,16);layout.setSpacing(12)
        heading=QHBoxLayout();logo=QLabel();logo.setFixedSize(48,48);logo.setPixmap(optical_icon(QIcon(str(branding_file('bitcoin-ui.png'))),44))
        heading.addWidget(logo);title=QLabel('Bitcoin Core Status');title.setObjectName('Title');heading.addWidget(title);heading.addStretch();layout.addLayout(heading)
        line=QHBoxLayout();self.light=QLabel('●');self.light.setStyleSheet('font-size:18px;color:#999;');line.addWidget(self.light)
        self.phase=QLabel('Checking local node…');self.phase.setStyleSheet('font-weight:600;');line.addWidget(self.phase,1)
        self.version=QLabel('Version —');self.version.setObjectName('Muted');line.addWidget(self.version);layout.addLayout(line)
        self.progress=QProgressBar();self.progress.setRange(0,1000);self.progress.setValue(0);self.progress.setFormat('Validation —');layout.addWidget(self.progress)
        self.sync_note=QLabel('Waiting for local Bitcoin Core RPC.');self.sync_note.setWordWrap(True);layout.addWidget(self.sync_note)
        grid=QGridLayout();grid.setSpacing(10);self.values={}
        for i,(key,label) in enumerate((('blocks','Validated blocks'),('headers','Known headers'),('peers','Connected peers'),('network','Bitcoin network'),('mempool','Mempool transactions'),('disk','Data disk free'))):
            box=QFrame();box.setObjectName('Metric');v=QVBoxLayout(box);v.setContentsMargins(14,10,14,10)
            caption=QLabel(label);caption.setObjectName('Muted');v.addWidget(caption)
            value=QLabel('—');value.setObjectName('Value');value.setAccessibleName(label);v.addWidget(value)
            self.values[key]=value;grid.addWidget(box,i//3,i%3)
        for col in range(3):grid.setColumnStretch(col,1)
        layout.addLayout(grid)
        self.context=QLabel('Privacy —   ·   Storage —');self.context.setWordWrap(True);layout.addWidget(self.context)
        self.transports=QLabel('Peer networks —');self.transports.setObjectName('Muted');self.transports.setWordWrap(True);layout.addWidget(self.transports)
        self.details_button=QPushButton('Show technical details');self.details_button.clicked.connect(self.show_details)
        layout.addWidget(self.details_button,0,Qt.AlignLeft)
        self.updated=QLabel('');self.updated.setObjectName('Muted');layout.addWidget(self.updated);layout.addStretch()
        buttons=QHBoxLayout();back=QPushButton('Go Back');back.setAccessibleName('Go Back to Settings');back.clicked.connect(self.go_back);buttons.addWidget(back)
        buttons.addStretch();self.refresh_button=QPushButton('Refresh');self.refresh_button.clicked.connect(self.poll);buttons.addWidget(self.refresh_button)
        close=QPushButton('Close Settings' if from_settings else 'Close');close.clicked.connect(self.close_settings);buttons.addWidget(close);layout.addLayout(buttons)
        self.timer=QTimer(self);self.timer.setInterval(3000);self.timer.timeout.connect(self.poll)
        self.pulse=QTimer(self);self.pulse.setInterval(500);self.pulse.timeout.connect(self.animate)
        if autostart:self.timer.start();self.pulse.start();QTimer.singleShot(0,self.poll)

    def show_details(self):
        from core_details_ui import TechnicalDetailsDialog
        from modeless import open_window
        owner=self.navigation_owner or self
        return open_window(owner,'core-technical-details',lambda:TechnicalDetailsDialog(self.latest))

    def poll(self):
        if self.closing or self.job is not None:return
        self.refresh_button.setEnabled(False);self.job=Worker(self);self.job.received.connect(self.apply)
        self.job.finished.connect(self.finished_poll);self.job.start()

    def finished_poll(self):
        job=self.job;self.job=None;job.deleteLater();self.refresh_button.setEnabled(True)
        if self.closing:super().reject()

    def animate(self):
        self.tick_count+=1
        if self.validating:self.light.setStyleSheet('font-size:18px;color:'+('#f7931a' if self.tick_count%2 else '#a96518')+';')

    def apply(self,data):
        if self.closing:return
        self.latest=data
        self.updated.setText('Updated '+time.strftime('%H:%M:%S',time.localtime(data.get('updated',time.time())))+' · Local data · Refreshes every 3 seconds')
        if not data.get('available'):
            self.validating=False;self.light.setStyleSheet('font-size:18px;color:#ed5d5d;')
            self.phase.setText('Core stopped' if data.get('service') in ('inactive','failed','deactivating') else 'Core starting or RPC unavailable')
            self.version.setText('Version —');self.progress.setRange(0,1000);self.progress.setValue(0);self.progress.setFormat('Validation unavailable')
            for label in self.values.values():label.setText('—')
            self.sync_note.setText('No live chain data is available. If a blockchain backup is running, let it finish, then start Bitcoin Core manually.')
            self.context.setText('Service: '+data.get('service','unknown'));self.transports.setText('No live peer data');return
        chain=data['chain'];net=data['net'];peers=int(net.get('connections',0));active=net.get('networkactive',False)
        self.validating=bool(chain.get('initialblockdownload') and active and peers)
        self.phase.setText('Network paused' if not active else 'No peers connected' if not peers else 'Downloading and validating' if self.validating else 'Synchronized')
        self.light.setStyleSheet('font-size:18px;color:'+('#f7931a' if self.validating else '#55d68b' if active and peers else '#999')+';')
        self.version.setText(str(net.get('subversion','Unknown')).strip('/').replace('Satoshi:','Bitcoin Core '))
        progress=max(0.0,min(1.0,float(chain.get('verificationprogress',0))))
        self.progress.setRange(0,1000);self.progress.setValue(round(progress*1000));self.progress.setFormat(f'Validation {progress:.2%}')
        blocks=int(chain.get('blocks',0));headers=int(chain.get('headers',0))
        self.sync_note.setText(f'{max(0,headers-blocks):,} known blocks still to validate.' if headers>blocks else 'Validated height matches known headers.'+(' Waiting for peers to verify the latest tip.' if not peers else ''))
        if data.get('presync',-1)>=0:self.sync_note.setText(self.sync_note.text()+f" Header pre-sync: {data['presync']:,}.")
        for key,value in {'blocks':f'{blocks:,}','headers':f'{headers:,}','peers':str(peers),'network':str(chain.get('chain','—')),
            'mempool':f"{data['mempool']['size']:,}" if 'size' in data.get('mempool',{}) else '—','disk':f"{data['free']/1024**3:.1f} GiB" if data.get('free') is not None else '—'}.items():self.values[key].setText(value)
        storage='Pruned' if chain.get('pruned') else 'Full history';size=chain.get('size_on_disk')
        self.context.setText('Privacy: '+str(data.get('privacy','Unknown'))+' · Storage: '+storage+(f' · {size/1024**3:.1f} GiB of blocks' if isinstance(size,(int,float)) else ''))
        self.transports.setText('Peer networks: '+(' · '.join(f'{k}: {v}' for k,v in sorted(data.get('transports',{}).items())) or 'None'))

    def go_back(self):
        owner=self.navigation_owner;self.reject()
        if owner and self.from_settings:owner.settings()

    def close_settings(self):
        owner=self.navigation_owner
        if owner and self.from_settings:
            root=getattr(owner,'settings_dialog',None)
            if root is not None:root.reject()
        self.reject()

    def reject(self):
        self.timer.stop();self.pulse.stop();self.closing=True
        if self.job is not None:self.hide()
        else:super().reject()

    def closeEvent(self,event):
        if self.job is not None:self.reject();event.ignore()
        else:self.timer.stop();self.pulse.stop();super().closeEvent(event)
