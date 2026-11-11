"""Beginner-friendly keyboard and mouse settings using native X11 controls."""
from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (QCheckBox,QComboBox,QDialog,QFormLayout,QHBoxLayout,QLabel,
 QPlainTextEdit,QPushButton,QScrollArea,QSlider,QSpinBox,QTabWidget,QVBoxLayout,QWidget)
import desktop_input as inputs
import pointer_control as pointer

class KeyboardMouseDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent)
        from ui import STYLE
        self.setWindowTitle('Keyboard and Mouse');self.setStyleSheet(STYLE)
        self.resize(760,640);self.setMinimumSize(540,440)
        self.job=None;self.devices=[];self.controls={};self.system=inputs.read_system_layout()
        self.layouts,self.models,_=inputs.catalog()
        self.data=inputs.load()
        box=QVBoxLayout(self);box.setContentsMargins(20,16,20,14)
        title=QLabel('Keyboard and Mouse');title.setObjectName('Title');box.addWidget(title)
        self.tabs=QTabWidget();self.tabs.setAccessibleName('Keyboard and Mouse settings');box.addWidget(self.tabs,1)
        self.keyboard_tab=self.page('Keyboard');self.mouse_tab=self.page('Mouse and Touchpad')
        self.build_keyboard();self.build_mouse()
        self.status=QLabel('');self.status.setWordWrap(True);self.status.setTextFormat(Qt.PlainText);box.addWidget(self.status)
        row=QHBoxLayout();self.save=QPushButton('Apply and Save');self.save.clicked.connect(self.apply)
        row.addWidget(self.save);row.addStretch(1)
        self.close_button=QPushButton('Back to Settings');self.close_button.clicked.connect(self.accept);row.addWidget(self.close_button)
        box.addLayout(row)
        for combo in self.findChildren(QComboBox):
            combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(20)
        self.refresh_devices()
        self.tabs.currentChanged.connect(lambda _:self.status.clear())

    def page(self,name):
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QScrollArea.NoFrame)
        page=QWidget();layout=QVBoxLayout(page);layout.setContentsMargins(14,12,14,12);layout.setSpacing(10)
        scroll.setWidget(page);self.tabs.addTab(scroll,name);return layout

    @staticmethod
    def explanation(layout,text):
        label=QLabel(text);label.setWordWrap(True);layout.addWidget(label)

    def build_keyboard(self):
        layout=self.keyboard_tab
        self.explanation(layout,'Choose how the keys on your keyboard behave. The layout decides which letters and symbols are typed. Changes apply to this desktop immediately; the saved layout also reaches the login screen after a restart.')
        form=QFormLayout();self.model=QComboBox();self.model.setAccessibleName('Keyboard model')
        for code,description in sorted(self.models.items(),key=lambda x:x[1] or x[0]):self.model.addItem(description or code,code)
        self.model.setCurrentIndex(max(0,self.model.findData(self.system['model'])))
        self.layout_box=QComboBox();self.layout_box.setAccessibleName('Keyboard layout')
        for code,value in sorted(self.layouts.items(),key=lambda x:x[1]['description']):self.layout_box.addItem(value['description'],code)
        self.layout_box.setCurrentIndex(max(0,self.layout_box.findData(self.system['layout'].split(',')[0])))
        self.variant=QComboBox();self.variant.setAccessibleName('Keyboard layout variant')
        self.layout_box.currentIndexChanged.connect(self.fill_variants);self.fill_variants()
        index=self.variant.findData(self.system['variant'].split(',')[0]);self.variant.setCurrentIndex(max(0,index))
        form.addRow('Keyboard model',self.model);form.addRow('Layout / language',self.layout_box);form.addRow('Variant',self.variant)
        layout.addLayout(form)
        self.explanation(layout,'“Default” suits most keyboards. A variant is an alternative arrangement, such as one with different accent keys. Existing advanced keyboard options are preserved.')
        self.repeat=QCheckBox('Repeat a letter while its key is held down');self.repeat.setChecked(self.data['keyboard']['repeat']);layout.addWidget(self.repeat)
        repeat_form=QFormLayout();self.delay=QSpinBox();self.delay.setRange(100,2000);self.delay.setSingleStep(50);self.delay.setSuffix(' ms');self.delay.setValue(self.data['keyboard']['delay_ms']);self.delay.setAccessibleName('Delay before key repeat')
        self.rate=QSpinBox();self.rate.setRange(1,60);self.rate.setSuffix(' per second');self.rate.setValue(self.data['keyboard']['rate_hz']);self.rate.setAccessibleName('Keyboard repeat speed')
        repeat_form.addRow('Wait before repeating',self.delay);repeat_form.addRow('Repeat speed',self.rate);layout.addLayout(repeat_form)
        self.repeat.toggled.connect(lambda value:(self.delay.setEnabled(value),self.rate.setEnabled(value)))
        self.delay.setEnabled(self.repeat.isChecked());self.rate.setEnabled(self.repeat.isChecked())
        self.numlock=QCheckBox('Turn Num Lock on when the desktop starts');self.numlock.setChecked(self.data['keyboard']['numlock']);layout.addWidget(self.numlock)
        self.explanation(layout,'Num Lock makes a number pad type digits. You can still turn it on or off with the key during a session. The login layout is saved, but repeat and Num Lock preferences belong to the desktop. An older encrypted installation may still use its original disk-unlock keyboard layout.')
        self.test=QPlainTextEdit();self.test.setPlaceholderText('After applying, type here to test letters, symbols and repeated keys. Do not enter passwords.');self.test.setAccessibleName('Test keyboard typing');self.test.setMaximumHeight(82);layout.addWidget(self.test)
        layout.addStretch(1)

    def fill_variants(self,*_):
        self.variant.clear()
        value=self.layouts.get(self.layout_box.currentData(),{})
        for code,description in value.get('variants',{}).items():self.variant.addItem(description,code)

    def build_mouse(self):
        layout=self.mouse_tab
        self.explanation(layout,'Choose a mouse or touchpad, then adjust the settings it supports. Bluetooth devices must first be connected in Bluetooth Devices. Saved choices return when the same device reconnects.')
        row=QHBoxLayout();self.devices_box=QComboBox();self.devices_box.setAccessibleName('Mouse device');row.addWidget(self.devices_box,1)
        refresh=QPushButton('Refresh Devices');refresh.clicked.connect(self.refresh_devices);row.addWidget(refresh);layout.addLayout(row)
        self.speed_text=QLabel('Pointer speed');layout.addWidget(self.speed_text)
        self.slider=QSlider(Qt.Horizontal);self.slider.setRange(-100,100);self.slider.setAccessibleName('Pointer speed; slower to faster');self.slider.valueChanged.connect(self.speed_label);layout.addWidget(self.slider)
        legend=QHBoxLayout();legend.addWidget(QLabel('Slower'));legend.addStretch();legend.addWidget(QLabel('Normal'));legend.addStretch();legend.addWidget(QLabel('Faster'));layout.addLayout(legend)
        captions={
          'left_handed':'Use the right button as the main button (left-handed)',
          'natural_scroll':'Natural scrolling — content follows your fingers',
          'tap_to_click':'Tap the touchpad to click',
          'disable_while_typing':'Ignore accidental touchpad movement while typing',
          'middle_emulation':'Press left and right together for a middle click',
        }
        for key,caption in captions.items():
            control=QCheckBox(caption);control.setAccessibleName(caption);self.controls[key]=control;layout.addWidget(control)
        form=QFormLayout()
        for key,label in [('acceleration','Pointer movement'),('scroll_method','Scrolling method')]:
            control=QComboBox();control.setAccessibleName(label);self.controls[key]=control;form.addRow(label,control)
        layout.addLayout(form)
        self.explanation(layout,'Adaptive movement travels farther when you move the mouse faster. Flat movement uses a steady relationship. A greyed-out option is not offered by this device; it is not an error. Scroll speed and click behaviour can also depend on the application.')
        layout.addStretch(1);self.devices_box.currentIndexChanged.connect(self.select_device)

    def refresh_devices(self):
        try:
            old=self.devices_box.currentData();self.devices=pointer.get_devices()
            self.devices_box.blockSignals(True);self.devices_box.clear()
            for device in self.devices:self.devices_box.addItem(device['name'],device['id'])
            index=self.devices_box.findData(old);self.devices_box.setCurrentIndex(max(0,index));self.devices_box.blockSignals(False)
            self.select_device()
        except (OSError,ValueError) as exc:self.status.setText(str(exc));self.devices=[];self.slider.setEnabled(False)

    def speed_label(self,*_):
        self.speed_text.setText(f'Pointer speed: {self.slider.value():+d} (0 = normal)')

    def select_device(self,*_):
        device=next((d for d in self.devices if d['id']==self.devices_box.currentData()),None)
        self.slider.setEnabled(device is not None)
        for control in self.controls.values():control.setEnabled(False)
        if not device:
            self.status.setText('No adjustable mouse is connected. Please connect one and use Refresh Devices.' if self.tabs.currentIndex()==1 else '');return
        try:
            self.slider.setValue(round(pointer.load_preferences().get(device['name'],device['speed'])*100));self.speed_label()
            choices=inputs.device_choices(inputs.properties(device['id']))
            saved=inputs.load()['devices'].get(device['name'],{})
            for key,control in self.controls.items():
                control.setEnabled(key in choices)
                if isinstance(control,QCheckBox):control.setChecked(saved.get(key,choices.get(key,False)))
                else:
                    control.clear();entry=choices.get(key,{'available':[]})
                    for option in entry['available']:control.addItem({'adaptive':'Adaptive','flat':'Flat (no acceleration)','two_finger':'Two fingers','edge':'Touchpad edge','button':'Hold a scroll button'}[option],option)
                    index=control.findData(saved.get(key,entry.get('value')));control.setCurrentIndex(max(0,index))
        except (OSError,ValueError) as exc:self.status.setText(str(exc))

    def apply(self):
        if self.job is not None:return
        if self.tabs.currentIndex()==1:
            device=next((d for d in self.devices if d['id']==self.devices_box.currentData()),None)
            if not device:self.status.setText('Please connect a mouse and choose Refresh Devices.');return
            try:
                if not any(d['id']==device['id'] and d['name']==device['name'] for d in pointer.get_devices()):
                    raise inputs.InputError('That mouse changed or disconnected. Please choose Refresh Devices.')
                settings={k:(c.isChecked() if isinstance(c,QCheckBox) else c.currentData()) for k,c in self.controls.items() if c.isEnabled()}
                speed=self.slider.value()/100;pointer.set_speed(device['id'],speed);inputs.apply_device(device['id'],settings)
                pointer.save_preference(device['name'],speed);data=inputs.load();data['devices'][device['name']]=settings;inputs.save(data)
                self.status.setText('Mouse settings applied and saved for '+device['name']+'.')
            except (OSError,ValueError) as exc:self.status.setText(str(exc))
            return
        try:
            self.pending_layout=inputs.validate_layout(dict(model=self.model.currentData(),layout=self.layout_box.currentData(),variant=self.variant.currentData(),options=self.system['options']))
            self.pending_keyboard=dict(repeat=self.repeat.isChecked(),delay_ms=self.delay.value(),rate_hz=self.rate.value(),numlock=self.numlock.isChecked())
            from ui import Job,admin
            self.save.setEnabled(False);self.tabs.setEnabled(False);self.close_button.setEnabled(False);self.status.setText('Saving keyboard settings…')
            self.job=Job(lambda:admin('keyboard-settings',self.pending_layout),self)
            self.job.success.connect(self.keyboard_saved);self.job.failure.connect(self.failed);self.job.finished.connect(self.job_finished);self.job.start()
        except (OSError,ValueError) as exc:self.status.setText(str(exc))

    @Slot(object)
    def keyboard_saved(self,result):
        try:
            inputs.apply_keyboard(self.pending_keyboard,layout=self.pending_layout)
            data=inputs.load();data['keyboard']=self.pending_keyboard;inputs.save(data);self.system=self.pending_layout
            self.status.setText('Keyboard settings applied and saved. Please test the keys above. The login screen uses the saved layout after restart.')
        except (OSError,ValueError) as exc:self.status.setText('The system layout was saved, but a desktop setting could not be applied: '+str(exc))

    @Slot(str)
    def failed(self,message):self.status.setText(message)

    @Slot()
    def job_finished(self):
        job=self.job;self.job=None
        self.save.setEnabled(True);self.tabs.setEnabled(True);self.close_button.setEnabled(True)
        if job is not None:job.deleteLater()

    def done(self,result):
        if self.job is not None:self.status.setText('Keyboard settings are being saved.');return
        self.test.clear();super().done(result)
