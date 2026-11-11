"""Always-visible system clock and one shared Date & Time settings dialog."""
from datetime import datetime
import time
from PySide6.QtCore import Qt, QDate, QTime, QDateTime, QTimeZone, QTimer, QSize, Slot
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QCompleter,
    QDateTimeEdit, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout)
from desktop_surface import HintButton
from system_time import TimeError, snapshot, validate_request, zone, zone_names


class ClockButton(HintButton):
    def __init__(self, home):
        super().__init__('', 'Date & Time: set the system clock, time zone and automatic time synchronization.',
                         home.show_card_help, home.hide_card_help)
        self.setObjectName('SystemClock')
        self.setAccessibleName('Date & Time')
        self.compact=False
        from ui import branding_file
        self.setIcon(QIcon(str(branding_file('icons/clock.svg'))))
        self.setIconSize(QSize(18, 18))
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet('''QPushButton#SystemClock {
            background:transparent; color:#b5b5b5; border:1px solid transparent;
            border-radius:7px; padding:2px 7px; font-size:12px;
        } QPushButton#SystemClock:hover { background:#202020; border-color:#555; }
          QPushButton#SystemClock:focus { border-color:#f7931a; color:#f2f2f2; }''')
        self.clicked.connect(home.date_time)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    def refresh(self):
        # Re-read /etc/localtime after a system-wide zone change; do not cache
        # startup TZ offsets or run a privileged process for each tick.
        time.tzset()
        now = datetime.now().astimezone()
        text = now.strftime('%d.%m.%Y.\n%H:%M' if self.compact else '%d.%m.%Y. · %H:%M')
        if self.text() != text:
            self.setText(text)
        self.setAccessibleDescription(now.strftime('%d.%m.%Y. %H:%M %Z') + '. Open Date & Time settings.')


class DateTimeDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        from ui import STYLE
        self.setWindowTitle('Date & Time')
        self.setStyleSheet(STYLE + '''
            QDateTimeEdit { background:#151515; color:#f2f2f2; border:1px solid #666; padding:8px; }
            QDateTimeEdit:focus { border:2px solid #f7931a; }
            QDateTimeEdit:disabled { color:#999; border-color:#444; }
        ''')
        self.resize(610, 520)
        self.job = None
        self.busy = False
        self.loaded = False
        self.saved = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        heading = QLabel('Date & Time'); heading.setObjectName('Title')
        layout.addWidget(heading)
        detail = QLabel('Set the clock for this computer. These settings remain after restart.')
        detail.setWordWrap(True); detail.setObjectName('Muted'); layout.addWidget(detail)
        self.live = QLabel(); self.live.setAlignment(Qt.AlignCenter)
        self.live.setStyleSheet('font-size:22px; font-weight:600; padding:8px;')
        layout.addWidget(self.live)
        label = QLabel('Time zone'); layout.addWidget(label)
        self.timezone = QComboBox()
        self.timezone.setAccessibleName('Time zone')
        self.timezone.setEditable(True); self.timezone.setInsertPolicy(QComboBox.NoInsert)
        names = zone_names(); self.timezone.addItems(names)
        completer = QCompleter(names, self.timezone)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        self.timezone.setCompleter(completer)
        self.timezone.setEnabled(False); label.setBuddy(self.timezone)
        layout.addWidget(self.timezone)
        self.automatic = QCheckBox('Set time automatically over the network')
        self.automatic.setEnabled(False); layout.addWidget(self.automatic)
        self.sync_status = QLabel('Reading system time settings…')
        self.sync_status.setWordWrap(True); self.sync_status.setObjectName('Muted')
        layout.addWidget(self.sync_status)
        manual_label = QLabel('Manual date and time'); layout.addWidget(manual_label)
        self.manual = QDateTimeEdit()
        self.manual.setTimeZone(QTimeZone(b'UTC'))
        self.manual.setAccessibleName('Manual date and time')
        self.manual.setDisplayFormat('dd.MM.yyyy HH:mm:ss')
        # UTC here keeps the editor's numeric fields independent of the
        # process time zone; the chosen IANA zone is validated by the backend.
        self.manual.setMinimumDateTime(QDateTime(QDate(2000, 1, 1), QTime(0, 0), Qt.UTC))
        self.manual.setMaximumDateTime(QDateTime(QDate(2100, 12, 31), QTime(23, 59, 59), Qt.UTC))
        self.manual.setKeyboardTracking(False)
        self.manual.setEnabled(False); manual_label.setBuddy(self.manual)
        layout.addWidget(self.manual)
        note = QLabel('For manual time, turn automatic time off. Network time uses the operating system’s connection and follows the selected network policy.')
        note.setObjectName('Muted'); note.setWordWrap(True); layout.addWidget(note)
        self.feedback = QLabel(''); self.feedback.setWordWrap(True)
        self.feedback.setTextFormat(Qt.PlainText); layout.addWidget(self.feedback)
        layout.addStretch()
        buttons = QHBoxLayout()
        self.back = QPushButton('Back'); self.back.clicked.connect(self.reject)
        self.apply = QPushButton('Apply'); self.apply.setEnabled(False)
        self.apply.clicked.connect(self.save)
        buttons.addWidget(self.back); buttons.addStretch(); buttons.addWidget(self.apply)
        layout.addLayout(buttons)
        self.automatic.toggled.connect(self.mode_changed)
        self.timezone.currentTextChanged.connect(self.zone_changed)
        self.timer = QTimer(self); self.timer.setInterval(1000)
        self.timer.timeout.connect(self.tick); self.timer.start()
        self.tick()
        QTimer.singleShot(0, self.load)

    def start(self, operation, success):
        from ui import Job
        # Jobs belong to QApplication so closing the read-only loading dialog
        # cannot destroy a running QThread or freeze the desktop.
        job = Job(operation, QApplication.instance())
        self.job = job
        job.success.connect(success)
        job.failure.connect(self.failed)
        job.finished.connect(self.job_finished)
        job.start()

    @Slot()
    def job_finished(self):
        job = self.sender()
        if self.job is job:
            self.job = None
        job.deleteLater()

    def load(self):
        self.start(snapshot, self.loaded_state)

    @Slot(object)
    def loaded_state(self, state):
        self.state = state
        index = self.timezone.findText(state['timezone'])
        if index < 0:
            self.timezone.addItem(state['timezone']); index = self.timezone.count() - 1
        self.timezone.setCurrentIndex(index)
        self.automatic.setChecked(state['automatic'])
        self.timezone.setEnabled(True)
        self.automatic.setEnabled(state['can_automatic'] or state['automatic'])
        self.loaded = True
        self.apply.setEnabled(True)
        self.mode_changed()
        if not state['automatic']:
            self.sync_status.setText('Manual time. Automatic synchronization is off.')
        elif state['synchronized']:
            self.sync_status.setText('Automatic time is on. The system clock is synchronized.')
        else:
            self.sync_status.setText('Automatic time is on. Waiting for a reachable time server.')

    def current_selected_time(self):
        return datetime.now(zone(self.timezone.currentText().strip()))

    def update_manual(self):
        try:
            now = self.current_selected_time()
            self.manual.setDateTime(QDateTime(QDate(now.year, now.month, now.day),
                                   QTime(now.hour, now.minute, now.second), Qt.UTC))
        except TimeError:
            pass

    def mode_changed(self, *_):
        self.manual.setEnabled(self.loaded and not self.automatic.isChecked() and not self.busy)
        self.update_manual()

    def zone_changed(self, *_):
        self.update_manual(); self.tick()

    def tick(self):
        time.tzset()
        self.live.setText(datetime.now().astimezone().strftime('%d.%m.%Y. · %H:%M:%S'))
        if self.loaded and self.automatic.isChecked():
            self.update_manual()

    def save(self):
        if self.busy or not self.loaded or self.job is not None:
            return
        request = {'timezone': self.timezone.currentText().strip(),
                   'automatic': self.automatic.isChecked()}
        if not request['automatic']:
            request['local_time'] = self.manual.dateTime().toString('yyyy-MM-dd HH:mm:ss')
        try:
            validate_request(request)
        except TimeError as exc:
            self.feedback.setText(str(exc)); return
        self.busy = True
        for control in (self.timezone, self.automatic, self.manual, self.apply, self.back):
            control.setEnabled(False)
        self.feedback.setText('Applying date and time settings…')
        from ui import admin
        self.start(lambda: admin('time-settings', request), self.applied)

    @Slot(object)
    def applied(self, result):
        self.busy = False; self.saved = True
        self.back.setEnabled(True)
        self.loaded_state(result['time'])
        self.feedback.setText('Date and time settings saved.')
        self.tick()
        home = self.parentWidget()
        if hasattr(home, 'clock'):
            home.clock.refresh()

    @Slot(str)
    def failed(self, message):
        self.busy = False; self.back.setEnabled(True)
        self.feedback.setText(message)
        if self.loaded:
            self.timezone.setEnabled(True)
            self.automatic.setEnabled(self.state['can_automatic'] or self.state['automatic'])
            self.manual.setEnabled(not self.automatic.isChecked())
            self.apply.setEnabled(True)
        else:
            self.sync_status.setText('System time settings could not be read.')

    def reject(self):
        if not self.busy:
            self.timer.stop(); super().reject()

    def closeEvent(self, event):
        if self.busy:
            event.ignore()
        else:
            self.timer.stop(); super().closeEvent(event)
