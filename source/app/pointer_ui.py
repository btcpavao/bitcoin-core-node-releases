"""Simple, per-device Bluetooth/USB pointer-speed control for Node Settings."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QComboBox,QDialog,QHBoxLayout,QLabel,QPushButton,
                               QSlider,QVBoxLayout)
import pointer_control as pointer

class PointerDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent)
        from ui import STYLE
        self.setWindowTitle('Mouse & Pointer')
        self.setStyleSheet(STYLE)
        self.resize(670,450)
        self.devices=[]
        self.setMinimumSize(550,420)
        layout=QVBoxLayout(self);layout.setContentsMargins(20,20,20,20);layout.setSpacing(12)
        heading=QLabel('Mouse & Pointer');heading.setObjectName('Title');layout.addWidget(heading)
        detail=QLabel('Adjust the pointer speed for a Bluetooth, USB or built-in mouse. Each connected device can have its own setting. Saved settings return after reconnecting or restarting.')
        detail.setWordWrap(True);layout.addWidget(detail)
        picker=QHBoxLayout()
        self.devices_box=QComboBox()
        self.devices_box.setAccessibleName('Mouse device')
        self.devices_box.currentIndexChanged.connect(self.selection_changed)
        picker.addWidget(self.devices_box,1)
        refresh=QPushButton('Refresh Devices');refresh.clicked.connect(self.refresh)
        picker.addWidget(refresh);layout.addLayout(picker)
        self.speed_text=QLabel('Pointer speed')
        layout.addWidget(self.speed_text)
        self.slider=QSlider(Qt.Orientation.Horizontal);self.slider.setRange(-100,100)
        self.slider.setTickInterval(20);self.slider.setTickPosition(QSlider.TicksBelow)
        self.slider.setAccessibleName('Pointer speed; slower to faster')
        self.slider.valueChanged.connect(self.speed_changed)
        layout.addWidget(self.slider)
        guide=QHBoxLayout()
        guide.addWidget(QLabel('Slower'));guide.addStretch(1)
        guide.addWidget(QLabel('Default'));guide.addStretch(1)
        guide.addWidget(QLabel('Faster'))
        layout.addLayout(guide)
        self.status=QLabel('');self.status.setWordWrap(True);self.status.setTextFormat(Qt.PlainText)
        layout.addWidget(self.status)
        row=QHBoxLayout()
        self.save=QPushButton('Apply and Save')
        self.save.clicked.connect(self.apply);row.addWidget(self.save)
        row.addStretch(1)
        close=QPushButton('Back to Settings');close.clicked.connect(self.accept);row.addWidget(close)
        layout.addLayout(row)
        self.refresh()

    def refresh(self):
        try:
            self.devices=pointer.get_devices()
            self.devices_box.blockSignals(True)
            old=self.devices_box.currentData()
            self.devices_box.clear()
            for dev in self.devices:
                self.devices_box.addItem(dev['name'],dev['id'])
            if old is not None:
                index=self.devices_box.findData(old)
                if index>=0:self.devices_box.setCurrentIndex(index)
            self.devices_box.blockSignals(False)
            if not self.devices:
                self.status.setText('No adjustable mouse is connected. Pair a Bluetooth mouse and click Refresh Devices.')
            self.selection_changed()
        except pointer.PointerError as exc:
            self.devices=[];self.status.setText(str(exc))
            self.save.setEnabled(False);self.slider.setEnabled(False)

    def selection_changed(self,*_):
        dev=next((d for d in self.devices if d['id']==self.devices_box.currentData()),None)
        enabled=dev is not None
        self.slider.setEnabled(enabled);self.save.setEnabled(enabled)
        if enabled:
            stored=pointer.load_preferences().get(dev['name'],dev['speed'])
            self.slider.blockSignals(True);self.slider.setValue(round(stored*100));self.slider.blockSignals(False)
            self.speed_changed()
            self.status.setText('Select a speed and choose Apply and Save. The change takes effect immediately.')

    def speed_changed(self,*_):
        v=self.slider.value()
        self.speed_text.setText(f'Pointer speed: {v:+d}  (0 is the normal libinput setting)')

    def apply(self):
        dev=next((d for d in self.devices if d['id']==self.devices_box.currentData()),None)
        if dev is None:return
        try:
            speed=self.slider.value()/100
            pointer.set_speed(dev['id'],speed)
            pointer.save_preference(dev['name'],speed)
            self.status.setText('Speed saved and applied to '+dev['name']+'. Reconnects and reboots use this setting.')
        except pointer.PointerError as exc:
            self.status.setText(str(exc))
