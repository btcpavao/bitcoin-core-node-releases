"""Local, responsive SVG explanations reused from Vault Guide. No network or wallet access."""
from __future__ import annotations

from html import escape
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPen, QPolygonF

COLORS = {
    'ink': '#f2f2f2', 'muted': '#c4c4c4', 'line': '#777777',
    'blue': '#8ecbff', 'amber': '#ffc47e', 'green': '#a5dfb0',
    'purple': '#d0b3ff',
}
FILLS = {'blue': '#142431', 'amber': '#2a2117', 'green': '#17271d',
         'purple': '#241c30', 'ink': '#202020'}

class Drawing:
    """Measured text and geometric shapes; labels never shrink to fit."""
    def __init__(self, width):
        self.width = int(width)
        self.parts = []
        self.bounds = []
        self.operations = []

    @staticmethod
    def metrics(size, bold=False, mono=False):
        font = QFont('DejaVu Sans Mono' if mono else 'DejaVu Sans')
        font.setPixelSize(size)
        font.setBold(bold)
        return QFontMetricsF(font)

    def lines(self, text, width, size=18, bold=False, mono=False):
        fm = self.metrics(size, bold, mono)
        result = []
        for paragraph in str(text).split('\n'):
            line = ''
            for word in paragraph.split(' '):
                candidate = (line + ' ' + word).strip()
                if line and fm.horizontalAdvance(candidate) > width:
                    result.append(line)
                    line = word
                else:
                    line = candidate
            result.append(line)
        return result

    def text_height(self, text, width, size=18, bold=False):
        return len(self.lines(text, width, size, bold)) * (size + 7)

    def text(self, x, y, text, width, size=18, color='ink', bold=False, mono=False):
        lines = self.lines(text, width, size, bold, mono)
        fm = self.metrics(size, bold, mono)
        for index, line in enumerate(lines):
            measured = fm.horizontalAdvance(line)
            self.operations.append(('text', (x, y + fm.ascent() + index * (size + 7), line, size, COLORS.get(color, color), bold, mono)))
            self.bounds.append((x, y + index * (size + 7), measured, size + 7))
            self.parts.append(
                '<text x="%g" y="%g" fill="%s" font-family="%s" font-size="%d" font-weight="%s">%s</text>' %
                (x, y + fm.ascent() + index * (size + 7), COLORS.get(color, color),
                 'DejaVu Sans Mono' if mono else 'DejaVu Sans', size,
                 '700' if bold else '400', escape(line)))
        return len(lines) * (size + 7)

    def rect(self, x, y, width, height, tone='ink', radius=10, dashed=False):
        self.operations.append(('rect', (x, y, width, height, radius, FILLS[tone], COLORS[tone] if tone != 'ink' else '#666666', dashed)))
        self.parts.append(
            '<rect x="%g" y="%g" width="%g" height="%g" rx="%d" fill="%s" stroke="%s" stroke-width="1.5"%s/>' %
            (x, y, width, height, radius, FILLS[tone], COLORS[tone] if tone != 'ink' else '#666666',
             ' stroke-dasharray="6 5"' if dashed else ''))

    def box_height(self, width, title, body=''):
        return 32 + self.text_height(title, width - 32, 20, True) + (
            8 + self.text_height(body, width - 32) if body else 0)

    def box(self, x, y, width, title, body='', tone='ink', height=None):
        height = height or self.box_height(width, title, body)
        self.rect(x, y, width, height, tone)
        top = y + 16
        top += self.text(x + 16, top, title, width - 32, 20, tone if tone != 'ink' else 'ink', True)
        if body:
            self.text(x + 16, top + 8, body, width - 32, color='muted')
        return height

    def arrow(self, x1, y1, x2, y2, tone='muted'):
        color = COLORS[tone]
        self.operations.append(('line', (x1, y1, x2, y2, color, 2)))
        self.parts.append('<path d="M %g %g L %g %g" fill="none" stroke="%s" stroke-width="2"/>' %
                          (x1, y1, x2, y2, color))
        if abs(y2 - y1) >= abs(x2 - x1):
            dy = -7 if y2 > y1 else 7
            points = [(x2 - 5, y2 + dy), (x2, y2), (x2 + 5, y2 + dy)]
        else:
            dx = -7 if x2 > x1 else 7
            points = [(x2 + dx, y2 - 5), (x2, y2), (x2 + dx, y2 + 5)]
        self.operations.append(('polyline', (points, color)))
        self.parts.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="2"/>' %
                          (' '.join('%g,%g' % p for p in points), color))

    def footer(self, y, text, tone='blue'):
        self.operations.append(('line', (1, y + 8, self.width - 1, y + 8, '#4a4a4a', 1)))
        self.parts.append('<path d="M 1 %g H %g" stroke="%s" stroke-width="1"/>' %
                          (y + 8, self.width - 1, '#4a4a4a'))
        return y + 26 + self.text(0, y + 26, text, self.width, color=tone, bold=True) + 8

    def pair(self, y, a, b):
        width = (self.width - 24) / 2
        height = max(self.box_height(width, a[0], a[1]), self.box_height(width, b[0], b[1]))
        self.box(1, y, width - 1, *a[:2], tone=a[2], height=height)
        self.box(width + 24, y, width - 1, *b[:2], tone=b[2], height=height)
        return y + height

    def paint(self, height, scale):
        # QTextBrowser displays a device-scale image. Draw the same measured
        # vector commands directly with Qt; no SVG decoder or network is needed.
        scale = max(1.0, min(3.0, float(scale)))
        image = QImage(round(self.width * scale), round(height * scale), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.scale(scale, scale)
        for kind, values in self.operations:
            if kind == 'text':
                x, y, text, size, color, bold, mono = values
                font = QFont('DejaVu Sans Mono' if mono else 'DejaVu Sans')
                font.setPixelSize(size); font.setBold(bold)
                painter.setFont(font); painter.setPen(QColor(color))
                painter.drawText(QPointF(x, y), text)
            elif kind == 'rect':
                x, y, w, h, radius, fill, stroke, dashed = values
                pen = QPen(QColor(stroke), 1.5)
                if dashed: pen.setStyle(Qt.PenStyle.DashLine)
                painter.setPen(pen); painter.setBrush(QColor(fill))
                painter.drawRoundedRect(QRectF(x, y, w, h), radius, radius)
            elif kind == 'line':
                x1, y1, x2, y2, color, weight = values
                painter.setPen(QPen(QColor(color), weight))
                painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
            else:
                points, color = values
                painter.setPen(QPen(QColor(color), 2)); painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPolyline(QPolygonF([QPointF(x, y) for x, y in points]))
        painter.end()
        image.setDevicePixelRatio(scale)
        return image

    def finish(self, height):
        height = int(height + 2)
        for x, y, w, h in self.bounds:
            if x < 0 or y < 0 or x + w > self.width + 1 or y + h > height + 1:
                raise ValueError('Guide illustration text exceeds its measured canvas')
        svg = '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">%s</svg>' % (
            self.width, height, self.width, height, ''.join(self.parts))
        return svg, height

def pairing(d, _):
    y = d.pair(1,
        ('Offline Vault', 'Private keys stay here.\nReview and sign transactions.', 'amber'),
        ('Online Node', 'Public descriptors only.\nWatch and prepare transactions.', 'blue'))
    y = d.box(1, y + 24, d.width - 2, 'Compare independently',
        'Receiving addresses + change addresses + next index + network', 'green') + y + 24
    return d.footer(y + 12, 'Public descriptors reveal activity, but cannot authorize spending.', 'muted')

def psbt(d, _):
    gap = 52
    width = (d.width - gap) / 2
    d.text(0, 1, 'ONLINE', width, 20, 'blue', True)
    d.text(width + gap, 1, 'OFFLINE VAULT', width, 20, 'amber', True)
    y = 43
    left = ('1  Prepare', 'Create an unsigned PSBT.')
    right = ('2  Review', 'Check destination, amount and transaction details.')
    h = max(d.box_height(width, *left), d.box_height(width, *right))
    d.box(1, y, width - 2, *left, tone='blue', height=h)
    d.box(width + gap + 1, y, width - 2, *right, tone='amber', height=h)
    d.arrow(width + 7, y + h / 2, width + gap - 7, y + h / 2)
    end_review = y + h
    y += h + 18
    y += d.text(0, y, 'PSBT files cross by removable media', width, 18, 'muted') + 20
    d.arrow(d.width - width / 2, end_review + 7, d.width - width / 2, y - 7)
    left = ('4  Broadcast', 'Publish the signed transaction from the online coordinator.')
    right = ('3  Sign', 'Sign in Core, then export the signed PSBT.')
    h = max(d.box_height(width, *left), d.box_height(width, *right))
    d.box(1, y, width - 2, *left, tone='blue', height=h)
    d.box(width + gap + 1, y, width - 2, *right, tone='amber', height=h)
    d.arrow(width + gap - 7, y + h / 2, width + 7, y + h / 2)
    return d.footer(y + h + 14, 'The PSBT transfer does not contain private keys.', 'green')

# Node-specific explanations use the same measured boxes, color roles and arrows.
PANELS = {
    'Bitcoin Core': ('Your node checks Bitcoin independently',
        ('Bitcoin peers', 'Supply blocks and transactions. Their claims are not trusted.', 'blue'),
        ('Your Bitcoin Core', 'Checks the rules and keeps the validated chain on disk.', 'green'),
        'Open Bitcoin Core to start. Exiting Core stops it; saved progress remains.'),
    'Synchronization': ('Two different kinds of progress',
        ('Blockchain validation', 'Core verifies blocks and transactions against Bitcoin rules.', 'blue'),
        ('Wallet scanning', 'Core finds transactions belonging to your public descriptors.', 'amber'),
        'Both must finish before preparing a payment. Pruning removes old blocks, not validation rules.'),
    'Networking': ('Connection and privacy have different controls',
        ('Network Status', 'Choose Wi-Fi, enter its password and connect. Advanced settings remain available.', 'blue'),
        ('Network & Privacy', 'Settings selects Clearnet, Tor P2P or whole-device WireGuard.', 'purple'),
        'Tor P2P does not route Debian updates. WireGuard enforces the configured full tunnel.'),
    'Backups & recovery': ('Four categories, one Backup and Restore menu',
        ('Chain + public wallets', 'Blockchain copies reuse validated data. Watch-only collections retain public wallet records.', 'blue'),
        ('Node + Core settings', 'Node configuration includes network and desktop preferences plus the portable Core subset.', 'green'),
        'Encryption is optional for wallet/settings exports. Keep the offline signing-wallet backup separately.'),
    'Persistent storage': ('Two places, different lifetimes',
        ('Both transfer folders · RAM', 'PSBT files and decrypted output and decrypted output disappear at restart or shutdown.', 'amber'),
        ('Disk and USB', 'Core wallets, blockchain and files saved outside the workspace remain.', 'blue'),
        'Save encrypted copies before shutdown. Restoring a wallet into Core creates a persistent copy.'),
    'Updates': ('Verify before activating',
        ('Download and verify', 'Explicitly select a supported release. Check signed hashes and trusted signers.', 'blue'),
        ('Approve and activate', 'Stop Core cleanly, snapshot local data and activate the verified release.', 'green'),
        'No automatic download or replacement. Keep an independent recovery backup.'),
    'Troubleshooting': ('Check the state before changing anything',
        ('Home status', 'Stopped: open Core. Waiting: check connections. Error: inspect Core and service diagnostics.', 'amber'),
        ('Settings → Bitcoin Core Status', 'Inspect peers, chain progress, wallet rescans and available disk space.', 'blue'),
        'Preserve data before investigating. Review PSBTs in Core; do not weaken a failed privacy profile.'),
}


FLOWS = {
 'Node configuration': ('Your setup travels; machine identity stays local', [
  ('1  Backup', 'Settings → Backup and Restore → Node configuration. Choose USB and optional encryption.', 'blue'),
  ('2  Review', 'On the new Node, choose the file. Check networks, time zone, privacy and omissions.', 'amber'),
  ('3  Restart to apply', 'Approve the review. Settings apply before networking on the next normal boot.', 'green')], 'Includes Wi-Fi secrets when saved. No wallets, blocks, login password or Bluetooth pairings.'),
 'Core configuration': ('Move Core preferences without network secrets', [
  ('1  Save preferences', 'Backup supported Core options and GUI choices; encryption is optional.', 'blue'),
  ('2  Review and stage', 'Inspect the option names on the target, then approve restoration.', 'amber'),
  ('3  Restart', 'Apply the portable subset. Wallets and blockchain are separate.', 'green')], 'Full Node configuration already includes these portable Core preferences.'),
 'Watch-only backups': ('Public-wallet collection, never signing authority', [
  ('1  Core running', 'Export supported watch-only wallets. Signing wallets are skipped.', 'blue'),
  ('2  Save to USB', 'One .json collection or an optionally encrypted .gpg backup.', 'amber'),
  ('3  Restore and check', 'Review names, restore with Core, compare addresses and finish rescanning.', 'green')], 'Existing wallets are never overwritten. Keep your offline Vault and its separate backups.'),
 'Blockchain backup': ('Reuse validated chain data', [
  ('1  Stop and copy', 'Core stops cleanly. Copy retained blocks and chainstate to USB.', 'blue'),
  ('2  Verify', 'Read back the copy. Core stays stopped until you start it manually.', 'amber'),
  ('3  Restore elsewhere', 'Select the latest completed backup. Validate before replacing the target chain.', 'green')], 'Not a wallet backup. Pruned copies cannot supply history already deleted.'),
 'Status & diagnostics': ('Compact dashboard; independent details window', [
  ('1  Live dashboard', 'Version, blocks, headers, peers, validation and storage from local Core.', 'blue'),
  ('2  Show technical details', 'A separate window: grouped fields, search, expand/collapse and optional raw JSON.', 'purple'),
  ('3  Refresh when ready', 'Inspect a stable snapshot without the data jumping as you read.', 'green')], 'Copy is explicit. Review private wallet names before sharing diagnostics.'),
 'Encrypt & Decrypt Files': ('USB input, verified files, RAM-only recovery', [
  ('1  Choose input', 'Places and USB / External media appear on the left. Click to mount or Refresh USB.', 'blue'),
  ('2  Encrypt or decrypt', 'Encryption saves a verified .gpg file. Decryption checks every required layer.', 'amber'),
  ('3  Save what you need', 'Recovered plaintext stays in Private Workspace. Copy required output before shutdown.', 'green')], 'Choosing a USB source does not change the RAM-only decryption destination.')
}

def flow(d, panels):
    y=1
    for i,(title,body,tone) in enumerate(panels):
        if i:
            d.arrow(d.width/2,y,d.width/2,y+18)
            y+=28
        y+=d.box(1,y,d.width-2,title,body,tone)
    return y


def render_visual(section, width, scale=1.0):
    d = Drawing(max(490, min(960, int(width))))
    if section in FLOWS:
        title,panels,description=FLOWS[section]
        height=flow(d,panels)
        height=d.footer(height+12,description)
    elif section == 'Watch-only wallets':
        title = 'Public view and private authority'
        description = 'Vault keeps the signing keys. Compare receiving and change addresses independently before pairing Node with its public export.'
        height = pairing(d, 1)
    elif section == 'PSBT transactions':
        title = 'Transaction files travel; private keys do not'
        description = 'Node prepares the PSBT. Vault independently reviews and signs it. Core opens the returned PSBT for review and explicit broadcast confirmation.'
        height = psbt(d, 1)
    else:
        title, left, right, description = PANELS[section]
        height = d.pair(1, left, right)
        height = d.footer(height + 12, description)
    svg, height = d.finish(height)
    return svg, d.width, height, title, description, d.paint(height, scale)
