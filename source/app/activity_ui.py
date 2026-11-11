"""Read-only, bounded node health polling and a small Home activity indicator."""
import subprocess
import time
import os
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget, QLabel, QProgressBar, QVBoxLayout
from rpc import CoreRPC, CoreError


def storage_usage():
    """Read space on Core's VERIFIED persistent datadir mount, not the root disk.

    Values include other files on that filesystem. Never present available
    space from a disconnected external drive as if it were the data drive.
    """
    try:
        from state import DATA, load_setup, verify_data_mount
        setup=load_setup()
        verify_data_mount(setup,DATA)
        filesystem=os.statvfs(DATA)
        total=filesystem.f_blocks*filesystem.f_frsize
        free=filesystem.f_bavail*filesystem.f_frsize
        if total<=0 or free<0 or free>total:
            return None
        return dict(total=total,free=free,used_percent=round(100*(total-free)/total),
                    free_percent=round(100*free/total))
    except (OSError,ValueError,RuntimeError,KeyError,TypeError):
        return None


def node_activity():
    result = subprocess.run(
        ['/usr/bin/systemctl', 'show', 'bitcoin-core-node.service',
         '--property=ActiveState,SubState,Result'],
        capture_output=True, text=True, timeout=3)
    if result.returncode:
        return 'error', 'Node status unavailable. Please check Node Settings → Node status.', False
    service = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    active = service.get('ActiveState')
    if active == 'failed':
        return 'error', 'Bitcoin Core encountered an error. Please check local service diagnostics.', False
    if active == 'inactive':
        return 'stopped', 'Bitcoin Core is stopped. Open Bitcoin Core to resume validation.', False
    if active in ('activating', 'deactivating'):
        return 'starting', ('Bitcoin Core is starting…' if active == 'activating' else 'Bitcoin Core is stopping…'), False
    if active != 'active':
        return 'error', 'Bitcoin Core status is unavailable.', False
    rpc = CoreRPC(timeout=2)
    try:
        chain = rpc('getblockchaininfo')
        network = rpc('getnetworkinfo')
        peers = rpc('getpeerinfo')
    except CoreError as exc:
        if exc.code == -28:
            return 'starting', 'Bitcoin Core is loading and verifying local data…', False
        return 'error', 'Bitcoin Core is running; local RPC status is unavailable. Please check Bitcoin Core.', False
    state,text,was_animating=chain_activity(chain,network,peers)
    # Keep the historical three-field contract for callers/tests of
    # chain_activity. Only the Home worker receives these additional optional
    # values. Bitcoin Core's own verificationprogress drives every segment.
    try:progress=max(0.0,min(1.0,float(chain['verificationprogress'])))
    except (ValueError,TypeError,KeyError):progress=None
    if state=='synchronized':progress=1.0
    return state,text,False,progress,storage_usage()


def chain_activity(chain, network, peers):
    """Show real startup stages, including Core's zero-block header pre-sync."""
    if not network.get('networkactive', False):
        return 'starting', 'Bitcoin Core network activity is paused. Enable it in Bitcoin Core to synchronize.', False
    # IBD alone is insufficient after a previously synchronized node falls behind.
    syncing = (chain['initialblockdownload'] or chain['blocks'] < chain['headers']
               or time.time() - chain.get('time', 0) > 90 * 60)
    connected = network.get('networkactive', False) and network.get('connections', 0) > 0
    if syncing:
        progress = max(0.0, min(1.0, chain['verificationprogress']))
        text = f'Blockchain download and validation in progress · {progress:.2%}'
        if not connected:
            text = 'Waiting for Bitcoin peers. Check your connection in Network Status.'
        else:
            presync = max((peer.get('presynced_headers', -1) for peer in peers), default=-1)
            count = network['connections']
            if presync > chain['headers']:
                text = f'Pre-syncing block headers · {presync:,} headers · {count} peers'
            elif chain['blocks'] == 0 and chain['headers'] > 0:
                text = f'Synchronizing block headers · {chain["headers"]:,} headers · {count} peers'
            elif chain['blocks'] == 0 and chain['headers'] == 0:
                text = f'Connected to {count} Bitcoin peers · waiting for block headers…'
            else:
                text += f' · {chain["blocks"]:,} blocks · {count} peers'
        return 'syncing', text, bool(connected)
    text = 'Blockchain synchronized. Wallet rescans are shown separately.'
    if not connected:
        text = 'Blockchain validated to the last known tip; no peer connections.'
    return 'synchronized', text, False


class ActivityIndicator(QWidget):
    """100 tiny segments, each representing 1% of Core's verification progress."""
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setFixedHeight(13)
        self.setMinimumWidth(300)
        self.setMaximumWidth(620)
        self.state='starting'
        self.progress=None
        self.setAccessibleName('Bitcoin blockchain validation progress')

    def set_state(self,state,animate=False,progress=None):
        # animate parameter is retained for compatibility, never used for a spinner.
        self.state=state
        self.progress=None if progress is None else max(0.0,min(1.0,float(progress)))
        self.setAccessibleName('Blockchain validation progress: '+
                               ('unavailable' if self.progress is None else f'{self.progress:.2%}'))
        self.update()

    def paintEvent(self,event):
        painter=QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing,False)
        count=100
        # No fake progress: fill *completed* integer percent only.
        complete=int(self.progress*100) if self.progress is not None else 0
        available=max(1,self.width())
        width=(available-(count-1))/count
        if width<1:width=max(.5,available/count)
        gap=1 if available>=200 else 0
        width=(available-gap*(count-1))/count
        for i in range(count):
            start=i*(width+gap)
            painter.fillRect(QRectF(start,1,max(.5,width),11),
                QColor('#f7931a' if i<complete else '#353535'))
        painter.end()


class StorageBar(QWidget):
    """A simple disk used/available bar for the actual blockchain filesystem."""
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setMaximumWidth(620)
        self.setFixedHeight(35)
        layout=QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(3)
        self.caption=QLabel('Checking blockchain disk space…')
        self.caption.setAlignment(Qt.AlignCenter)
        self.caption.setTextFormat(Qt.PlainText)
        self.caption.setStyleSheet('color:#bfbfbf;font-size:11px;')
        self.bar=QProgressBar(self)
        self.bar.setRange(0,100)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(10)
        self.bar.setStyleSheet('QProgressBar { background:#353535; border:0; border-radius:3px; } '
                               'QProgressBar::chunk { background:#f7931a; border-radius:3px; }')
        layout.addWidget(self.caption)
        layout.addWidget(self.bar)

    def update_space(self,reading):
        if reading is None:
            self.setVisible(False)
            return
        free,total=reading['free'],reading['total']
        free_percent=reading['free_percent']
        gib=1024**3
        self.caption.setText(
            f'Blockchain disk · {free_percent}% free · {free/gib:.1f} GiB available of {total/gib:.1f} GiB')
        self.caption.setAccessibleName(self.caption.text())
        used=reading['used_percent']
        self.bar.setValue(used)
        color='#FF5151' if free_percent<=10 else '#f7931a'
        self.bar.setStyleSheet('QProgressBar { background:#353535; border:0; border-radius:3px; } '
                               f'QProgressBar::chunk {{ background:{color}; border-radius:3px; }}')
        self.setVisible(True)
