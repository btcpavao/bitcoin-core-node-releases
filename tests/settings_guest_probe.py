#!/usr/bin/python3
"""Actual Settings acceptance in an owned, disposable QEMU desktop session.

Run as the normal node/vault desktop user from its terminal, with
SETTINGS_VM_ACCEPTANCE=1. The FAT test medium must contain SETTINGS-TEST-ONLY
whose contents are exactly 'disposable QEMU fixture'. Initial phase changes
only the guest's device preferences/display and briefly exercises Vault's
manual system clock, then restores the clock. Reboot phase checks persistence
or reset before changing anything. No GUI/backend mocks or offscreen platform
are used. No wallet is opened and no network/radio is enabled.

Initial phase measures the attached ISO bytes through /dev/sr0. Reboot may use
the initial measured provenance if the ISO has been removed; that distinction
is explicit in the JSON. The host controller independently verifies the ISO.
"""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import pwd
import re
import runpy
import stat
import subprocess
import sys
import time
import traceback


def require(value, message):
    if not value:
        raise RuntimeError(message)


def command(argv, *, check=True, timeout=20, **kwargs):
    return subprocess.run(argv, check=check, capture_output=True, text=True,
                          timeout=timeout, env=dict(os.environ, LC_ALL='C', LANG='C'), **kwargs)


def digest(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def write_json(path, data):
    temporary = path.with_suffix(path.suffix+'.new')
    with temporary.open('w') as stream:
        json.dump(data, stream, indent=2, sort_keys=True)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, path)


class Probe:
    def __init__(self, args):
        self.args = args
        self.media = Path(args.media).resolve(strict=True)
        self.prefix = 'settings-'+args.product+'-'+args.run_id
        self.report_path = self.media/(self.prefix+'-'+args.phase+'-result.json')
        self.state_path = self.media/(self.prefix+'-state.json')
        self.export_path = self.media/(self.prefix+'-device-settings.json')
        self.app = self.home = self.menu = self.display_dialog = None
        self.windows = []
        self.report = dict(kind='bitcoin-core-settings-guest-v1', product=args.product,
                           phase=args.phase, run_id=args.run_id, status='running', checks=[],
                           started_utc=datetime.now(timezone.utc).isoformat(),
                           boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                           limitations=['Single-output QEMU cannot prove physical cable hotplug, mirror or extend behavior.'])

    def checkpoint(self):
        write_json(self.report_path, self.report)

    def passed(self, name, **evidence):
        self.report['checks'].append(dict(name=name, status='passed', evidence=evidence))
        self.checkpoint()
        print('PASS '+name, flush=True)

    def wait(self, predicate, seconds=40, description='guest UI operation'):
        deadline = time.monotonic()+seconds
        while time.monotonic() < deadline:
            self.app.processEvents()
            value = predicate()
            if value:
                return value
            time.sleep(.025)
        raise RuntimeError('Timed out waiting for '+description)

    def context(self):
        a = self.args
        require(os.environ.get('SETTINGS_VM_ACCEPTANCE') == '1', 'Explicit disposable-VM test environment required.')
        require(os.getuid() == pwd.getpwnam(a.product).pw_uid and os.geteuid() != 0,
                'Please run as the normal '+a.product+' desktop user, not root.')
        vendor = Path('/sys/devices/virtual/dmi/id/sys_vendor').read_text().strip()
        model = Path('/sys/devices/virtual/dmi/id/product_name').read_text().strip()
        require('QEMU' in vendor or 'Q35' in model, 'This probe only runs in an owned QEMU fixture.')
        require((self.media/'SETTINGS-TEST-ONLY').read_text().strip() == 'disposable QEMU fixture',
                'The test-media ownership marker is missing.')
        mounts = json.loads(command(['/usr/bin/findmnt','--json','--target',str(self.media),
                                    '--output','TARGET,SOURCE,FSTYPE']).stdout)['filesystems']
        require(len(mounts) == 1 and mounts[0]['fstype'] == 'vfat', 'Writable FAT test media required.')
        require(os.environ.get('DISPLAY') and os.environ.get('QT_QPA_PLATFORM','xcb') == 'xcb',
                'The real active X11 desktop is required; offscreen testing is not acceptance.')
        interfaces = sorted(p.name for p in Path('/sys/class/net').iterdir())
        require(interfaces == ['lo'], 'This disposable fixture must have no network adapters.')
        live = 'boot=live' in Path('/proc/cmdline').read_text().split()
        if a.product == 'node':
            require(not live and Path('/etc/bitcoin-core-node/installed').is_file(),
                    'Node acceptance requires its installed desktop.')
        self.report['guest'] = dict(uid=os.getuid(), user=a.product, vendor=vendor, model=model,
                                    live=live, interfaces=interfaces, media=mounts[0])
        self.checkpoint()

    def iso(self, previous=None):
        a = self.args
        path = Path(a.iso_device)
        no_medium = not path.exists()
        if path.exists():
            size_file = Path('/sys/class/block')/path.name/'size'
            no_medium = size_file.is_file() and size_file.read_text().strip() == '0'
        if a.phase == 'reboot' and no_medium:
            prior = previous['iso']
            require(prior['sha256'] == a.iso_sha256 and prior['bytes'] == a.iso_bytes
                    and prior['method'] == 'read-attached-optical-device', 'Initial ISO provenance does not match.')
            self.report['iso'] = dict(sha256=prior['sha256'], bytes=prior['bytes'],
                                      method='verified-in-prior-boot', initial_boot_id=previous['boot_id'])
            self.passed('ISO provenance retained from measured initial boot', **self.report['iso'])
            return
        require(re.fullmatch(r'/dev/sr[0-9]+', str(path)), 'Only an explicitly attached optical ISO device is read.')
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb', buffering=0) as source:
            require(stat.S_ISBLK(os.fstat(source.fileno()).st_mode), 'The ISO source must be an optical block device.')
            result = hashlib.sha256(); remaining = a.iso_bytes
            while remaining:
                chunk = source.read(min(8*1024*1024, remaining))
                require(chunk, 'The attached ISO ended before the expected byte count.')
                result.update(chunk); remaining -= len(chunk)
        actual = result.hexdigest()
        require(actual == a.iso_sha256, 'The actual attached ISO SHA256 does not match the candidate.')
        self.report['iso'] = dict(sha256=actual, bytes=a.iso_bytes, source=str(path),
                                  method='read-attached-optical-device')
        self.passed('Attached ISO bytes match the exact candidate', **self.report['iso'])

    def runtime(self, previous=None):
        product = self.args.product
        self.lib = Path('/usr/lib/bitcoin-core-node' if product == 'node' else '/usr/lib/core-vault/settings')
        sys.path.insert(0, str(self.lib)); sys.path.insert(0, '/usr/share/core-desktop')
        self.display = importlib.import_module('core_display')
        self.profiles = importlib.import_module('device_profile_data')
        self.inputs = importlib.import_module('desktop_input' if product == 'node' else 'vault_input')
        self.pointer = importlib.import_module('pointer_control' if product == 'node' else 'vault_pointer')
        files = [self.lib/'device_profile_data.py', self.lib/'device_profiles.py',
                 Path('/usr/share/core-desktop/core_display.py'), Path('/usr/share/core-desktop/core_display_settings.py'),
                 Path('/usr/local/bin/core-display-settings'), Path('/usr/local/bin/core-display-scale'),
                 Path('/usr/local/bin/core-'+product+'-session')]
        if product == 'node':
            files += [self.lib/'ui.py', self.lib/'launcher_ui.py', self.lib/'input_ui.py']
        else:
            files += [Path('/usr/local/bin/core-vault-home'), self.lib/'vault_settings.py',
                      self.lib/'vault_input_ui.py', self.lib/'vault_time.py',
                      Path('/usr/local/libexec/core-vault-time'),
                      Path('/usr/share/polkit-1/actions/org.bitcoin-core-vault.time.policy'),
                      Path('/etc/polkit-1/rules.d/49-core-vault-time.rules')]
            importlib.import_module('vault_input_guard').require_ram_home()
        hashes, protected = {}, []
        for path in files:
            try:
                hashes[str(path)] = digest(path)
            except PermissionError:
                # Debian protects rules.d from the ordinary desktop user. Do
                # not weaken that policy just to hash its contents in this QA.
                require(product == 'vault' and str(path) == '/etc/polkit-1/rules.d/49-core-vault-time.rules',
                        'An ordinary Settings runtime file is unexpectedly unreadable: '+str(path))
                item = dict(path=str(path), content_read='permission-denied')
                for name, target in (('file_stat', path), ('directory_stat', path.parent)):
                    try:
                        info = target.stat()
                    except PermissionError:
                        item[name] = 'permission-denied'
                    else:
                        item[name] = dict(uid=info.st_uid, gid=info.st_gid,
                                          mode=oct(stat.S_IMODE(info.st_mode)))
                protected.append(item)
        self.report['protected_runtime_files'] = protected
        if protected:
            self.report['limitations'].append(
                'The normal desktop user cannot hash the protected Polkit time rule. '
                'Its contents require host-side image/manifest verification; '
                'this probe still exercises the real authorized helper.')
        if previous is not None:
            require(hashes == previous['runtime_sha256'], 'Installed Settings payload changed between acceptance boots.')
            require(protected == previous.get('protected_runtime_files', []),
                    'Protected Settings runtime access or observed metadata changed between acceptance boots.')
        self.report['runtime_sha256'] = hashes
        self.backend = self.display.Backend()
        self.initial_snapshot = self.backend.probe(transforms=True)
        require(self.initial_snapshot.active, 'No actual active XRandR display was found.')
        self.report['display_hardware'] = self.initial_snapshot.hardware()
        self.passed('Installed runtime imports and real XRandR query succeed',
                    outputs=[o.name for o in self.initial_snapshot.active], files=len(hashes))

    def gui(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtWidgets import QApplication, QPushButton
        self.QPushButton = QPushButton
        self.app = QApplication([]); self.app.setQuitOnLastWindowClosed(False)
        require(self.app.platformName() == 'xcb', 'The actual X11 Qt platform is required.')
        if self.args.product == 'node':
            import ui
            ui.configure_ui(self.app); self.home = ui.Home()
        else:
            source = '/usr/local/bin/core-vault-home'
            original = sys.argv
            try:
                sys.argv = [source]  # Real mode; deliberately no --preview/--self-test.
                namespace = runpy.run_path(source, run_name='guest_vault_home')
            finally:
                sys.argv = original
            self.home = namespace['VaultHome']()
        self.home.show(); self.app.processEvents()
        controls = (self.home.settings_button,self.home.restart_button,self.home.shutdown_button)
        points = [button.mapTo(self.home, QPoint()) for button in controls]
        require([p.x() for p in points] == sorted(p.x() for p in points), 'Footer order must be Settings, Restart, Shutdown.')
        require(len({p.y() for p in points}) == 1, 'Footer controls must share the same row.')
        for button, point in zip(controls, points):
            require(button.width() == 48 and button.height() == 48 and not button.icon().isNull(), 'Footer control icon/size is wrong.')
            require(0 <= point.x() <= self.home.width()-button.width()
                    and 0 <= point.y() <= self.home.height()-button.height(), 'Footer control is outside the real screen.')
        self.capture(self.home, 'home')
        self.home.settings_button.click(); self.app.processEvents()
        self.menu = self.registry().get('settings')
        require(self.menu is not None and self.menu.isVisible() and not self.menu.isModal(), 'Gear must open modeless Settings.')
        self.home.settings_button.click(); self.app.processEvents()
        require(self.registry().get('settings') is self.menu, 'Repeated gear action created duplicate Settings.')
        common = {'Display Settings','Keyboard and Mouse','Date & Time','Backup and Restore'}
        expected = common if self.args.product == 'vault' else common | {
            'Network Connections','Bitcoin Core Network & Privacy','Bitcoin Core Status',
            'Bluetooth Devices','Login Password','Software Updates'}
        require(set(self.menu.cards) == expected, 'Actual Settings cards do not match the product policy.')
        buttons = {b.text() for b in self.menu.findChildren(QPushButton)}
        require({'Export device settings…','Import device settings…'} <= buttons, 'Both USB device-profile actions must be present.')
        self.capture(self.menu, 'settings')
        self.passed('Real Home gear opens one Settings window with correct product cards',
                    cards=list(self.menu.card_order), actual_screen=[self.home.width(),self.home.height()])
        self.menu.cards['Display Settings'].click()
        self.display_dialog = self.registry().get('display_settings')
        require(self.display_dialog is not None, 'Display card did not open the shared Display Settings window.')
        self.wait(lambda: self.display_dialog.snapshot is not None and not self.display_dialog.busy(),
                  description='actual display detection')
        require(self.display_dialog.apply_button.isEnabled(), self.display_dialog.status.text())
        self.capture(self.display_dialog, 'display')
        self.passed('Display Settings uses actual connected-output controls',
                    detected=list(self.display_dialog.rows))

    def registry(self):
        return getattr(self.home, '_modeless_windows' if self.args.product == 'node' else '_settings_windows', {})

    def capture(self, widget, suffix):
        path = self.media/(self.prefix+'-'+self.args.phase+'-'+suffix+'.png')
        require(widget.grab().save(str(path)), 'Could not save the actual Qt screenshot.')

    def display_change(self, layout, decision):
        dialog = self.display_dialog
        self.wait(lambda: not dialog.busy(), description='display ready')
        dialog.stage_profile(self.display.make_profile(self.args.product, self.backend.probe(), layout))
        require(dialog.requested_layout() == self.display.validate_layout(layout),
                'The actual Display Settings controls did not stage the requested test layout.')
        dialog.apply_button.click()
        self.wait(lambda: dialog.confirmation is not None or dialog.last_result == 'error',
                  description='actual Keep/Revert confirmation')
        require(dialog.confirmation is not None, dialog.status.text())
        self.capture(dialog.confirmation, 'confirm-'+decision)
        if decision != 'timeout':
            title = 'Keep changes' if decision == 'keep' else 'Revert'
            next(b for b in dialog.confirmation.findChildren(self.QPushButton) if b.text() == title).click()
        self.wait(lambda: dialog.job is None and dialog.last_result in ('kept','reverted','error'),
                  seconds=35, description='display '+decision)
        require(dialog.last_result == ('kept' if decision == 'keep' else 'reverted'), dialog.status.text())
        self.wait(lambda: not dialog.busy(), description='display refresh after '+decision)

    def exercise_display(self):
        snapshot = self.backend.probe()
        original = self.display.layout_from_snapshot(snapshot, 'auto')
        def active_state(value):
            return sorted((o.name,o.mode,o.rate,o.x,o.y,o.rotation,o.primary) for o in value.active)
        before = active_state(snapshot)
        original_dpi = self.backend.capture_scale()
        require(len(snapshot.active) == 1, 'This fixture expects one active display; use a dedicated multi-display probe for other layouts.')
        output = snapshot.active[0]
        choices = [m for m in output.modes if m.name != output.mode and m.width >= 800 and m.height >= 600]
        require(choices, 'QEMU did not expose a second usable resolution for actual rollback testing.')
        roomy = [m for m in choices if m.width >= 1000 and m.height >= 750]
        alternative = min(roomy or choices, key=lambda m: abs(m.width-1024)+abs(m.height-768))
        layout = copy.deepcopy(original)
        layout['scale'] = '1.25'
        layout['outputs'][0].update(mode=alternative.name, rate=alternative.rates[0], rotation='normal')
        for decision in ('revert','timeout'):
            self.display_change(layout, decision)
            require(active_state(self.backend.probe()) == before,
                    'The real prior mode and primary-output state were not restored after '+decision+'.')
            require(abs(self.backend.capture_scale()-original_dpi) < .01,
                    'The real prior interface size was not restored after '+decision+'.')
            self.passed('Actual display '+decision+' restores the working mode', resolution=output.mode)
        self.display_change(layout, 'keep')
        require(self.display.active_matches(layout, self.backend.probe()), 'Kept display mode was not applied.')
        saved = self.display.load_saved(self.args.product)
        require(saved is not None and saved['layout'] == layout, 'Keep did not save the reviewed display profile.')
        self.home.refresh_launch_environment()
        env = json.loads(command(['/usr/bin/python3','-c',
            'import json,os;print(json.dumps({k:os.environ.get(k) for k in ("GDK_SCALE","GDK_DPI_SCALE","QT_SCALE_FACTOR")}))']).stdout)
        wanted = self.display.launch_environment()
        require(env['GDK_SCALE'] == wanted.get('GDK_SCALE') and env['GDK_DPI_SCALE'] == wanted.get('GDK_DPI_SCALE')
                and env['QT_SCALE_FACTOR'] is None, 'Reopened applications inherit stale scale variables.')
        scale_record = json.loads((Path(os.environ['XDG_RUNTIME_DIR'])/'core-display-scale.json').read_text())
        effective = scale_record['scale']
        require(abs(self.backend.capture_scale()-float(effective)*96) < .01,
                'The confirmed interface size did not reach the actual X resource database.')
        self.passed('Actual Keep saves the layout and new processes receive current scale',
                    resolution=alternative.name, requested_scale='1.25', effective_scale=effective, launch_environment=env)
        return saved

    def input_window(self):
        module = importlib.import_module('input_ui' if self.args.product == 'node' else 'vault_input_ui')
        dialog = module.KeyboardMouseDialog(self.menu)
        dialog.show(); self.windows.append(dialog); self.app.processEvents()
        return dialog

    def keyboard(self, delay):
        dialog = self.input_window()
        dialog.tabs.setCurrentIndex(0); dialog.repeat.setChecked(True); dialog.delay.setValue(delay)
        dialog.save.click()
        self.wait(lambda: dialog.job is None and 'applied' in dialog.status.text().lower(),
                  description='actual keyboard save (last status: '+dialog.status.text()+')')
        require(self.inputs.load()['keyboard']['delay_ms'] == delay, 'Keyboard preference was not saved through the actual backend.')
        actual = command(['/usr/bin/xset','q']).stdout
        match = re.search(r'auto repeat delay:\s*(\d+)', actual)
        require(match and int(match[1]) == delay, 'The X server did not receive the keyboard repeat delay.')
        self.capture(dialog, 'keyboard-'+str(delay)); dialog.accept(); self.app.processEvents()

    def picker_click(self, button, path):
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QFileDialog
        pending = {'done':False,'error':None,'picker':None}
        timer = QTimer(); timer.setInterval(100)
        deadline = time.monotonic()+12
        def choose():
            dialogs = [w for w in self.app.topLevelWidgets() if isinstance(w, QFileDialog) and w.isVisible()]
            if time.monotonic() >= deadline:
                pending['error'] = 'The actual USB file chooser did not finish.'
                for picker in dialogs:
                    picker.reject()
                timer.stop(); return
            if dialogs:
                picker = dialogs[-1]
                if pending['picker'] is not picker:
                    pending['picker'] = picker
                    picker.setDirectory(str(path.parent))
                    return  # The real asynchronous model can reset the filename.
                if Path(picker.directory().absolutePath()) != path.parent:
                    picker.setDirectory(str(path.parent))
                    return
                if picker.selectedFiles() != [str(path)]:
                    picker.selectFile(str(path))
                    return
                self.capture(picker, 'usb-picker-'+('save' if 'Export' in button.text() else 'open'))
                picker.accept()
                if not picker.isVisible():
                    pending['done'] = True; timer.stop()
        timer.timeout.connect(choose); timer.start()
        button.click()  # Runs the real modal file chooser; timer selects its file.
        timer.stop(); require(pending['done'] and pending['error'] is None, pending['error'] or 'File chooser did not finish.')

    def exercise_profiles(self):
        self.keyboard(650)
        self.display_dialog.back_button.click(); self.app.processEvents()
        self.display_dialog = None
        profiles = self.home.device_profiles('export'); self.app.processEvents()
        require(not self.export_path.exists(), 'Use a new run-id; an export from this initial run already exists.')
        self.picker_click(profiles.export_button, self.export_path)
        require(self.export_path.is_file(), profiles.feedback.text())
        exported = self.profiles.read(self.export_path, self.args.product)
        require(exported['input']['preferences']['keyboard']['delay_ms'] == 650 and exported['display'] is not None,
                'Export did not contain the actual current input and saved display preferences.')
        original_hash = digest(self.export_path)
        try:
            self.profiles.write(self.export_path, exported, self.args.product)
        except FileExistsError:
            pass
        else:
            raise RuntimeError('Export unexpectedly overwrote an existing destination.')
        require(digest(self.export_path) == original_hash, 'Existing device profile bytes changed.')
        self.keyboard(750)
        self.picker_click(profiles.import_button, self.export_path)
        require(profiles.profile is not None and profiles.apply.isEnabled(), profiles.feedback.text())
        profiles.apply.click()
        self.wait(lambda: profiles.job is None and profiles.feedback.text().startswith('Input preferences applied.'),
                  description='actual USB profile import')
        require(self.inputs.load()['keyboard']['delay_ms'] == 650, 'USB input import did not restore the exported setting.')
        before = self.display.layout_from_snapshot(self.backend.probe())
        stored_before = digest(self.display.profile_path(self.args.product))
        profiles.displays.click(); self.app.processEvents()
        self.display_dialog = self.registry().get('display_settings')
        require(self.display_dialog is not None, profiles.feedback.text())
        self.wait(lambda: self.display_dialog.snapshot is not None and not self.display_dialog.busy(), description='imported display review')
        require(self.display.active_matches(before,self.backend.probe())
                and digest(self.display.profile_path(self.args.product)) == stored_before,
                'Reviewing a USB display profile changed or saved the display before confirmation.')
        self.capture(profiles, 'profile-review')
        self.display_dialog.back_button.click(); self.app.processEvents(); self.display_dialog = None
        profiles.back.click(); self.app.processEvents()
        self.passed('Actual USB export/import applies input and only stages display choices',
                    file=self.export_path.name, sha256=original_hash, keyboard_delay_ms=650)
        return exported

    def vault_time(self):
        module = importlib.import_module('vault_time')
        old_hash = digest('/etc/localtime')
        old_zone = module.snapshot()['timezone']
        selected = 'Europe/Zagreb' if old_zone != 'Europe/Zagreb' else 'Etc/UTC'
        base_clock, base_monotonic = time.time(), time.monotonic()
        def apply(epoch):
            local = datetime.fromtimestamp(epoch, module.zone(selected)).strftime('%Y-%m-%d %H:%M:%S')
            reply = command(['/usr/bin/pkexec','--disable-internal-agent','/usr/local/libexec/core-vault-time'],
                            input=json.dumps(dict(timezone=selected, local_time=local)), timeout=35)
            value = json.loads(reply.stdout)
            require(value.get('ok') is True, 'The actual privileged time helper did not confirm success.')
        try:
            apply(base_clock+120)
            require(abs(time.time()-(base_clock+120+time.monotonic()-base_monotonic)) < 10,
                    'The actual guest system clock did not change as requested.')
        finally:
            apply(base_clock+time.monotonic()-base_monotonic)
        require(abs(time.time()-(base_clock+time.monotonic()-base_monotonic)) < 10,
                'The disposable guest clock was not restored after its test.')
        require(module.snapshot()['timezone'] == selected, 'Session timezone preference was not applied.')
        mounts = json.loads(command(['/usr/bin/findmnt','--json','--mountpoint','/etc/localtime',
                                    '--output','TARGET,SOURCE,FSTYPE']).stdout)['filesystems']
        require(len(mounts) == 1 and mounts[0]['fstype'] == 'tmpfs', 'Vault timezone was not overlaid from RAM.')
        require(digest('/etc/localtime') == digest('/usr/share/zoneinfo/'+selected), 'The active localtime data is wrong.')
        require(sorted(p.name for p in Path('/sys/class/net').iterdir()) == ['lo'], 'A network interface appeared in Vault.')
        self.passed('Actual local-session Polkit helper applies manual clock and RAM timezone',
                    timezone=selected, timezone_mount=mounts[0], clock_restored=True)
        return dict(original_zone=old_zone, original_localtime_sha256=old_hash, test_zone=selected)

    def reboot_checks(self, previous):
        require(self.report['boot_id'] != previous['boot_id'], 'Reboot acceptance must run after a real guest reboot.')
        require(digest(self.export_path) == previous['export_sha256'], 'USB device profile changed across reboot.')
        if self.args.product == 'node':
            require(self.inputs.load() == previous['input_preferences'], 'Node input preferences did not persist.')
            saved = self.display.load_saved('node')
            require(saved == previous['display_profile'], 'Node confirmed display profile did not persist.')
            if all(row['edid'] is not None for row in saved['hardware']):
                require(self.display.active_matches(saved['layout'],self.backend.probe()),
                        'Node did not replay its matching confirmed display layout.')
                replay = 'confirmed against actual XRandR state'
            else:
                replay = 'automatic replay intentionally skipped for an output without EDID'
                self.report['limitations'].append('QEMU output lacks EDID; this run proves saved display preferences but not automatic layout replay.')
            self.passed('Node input and confirmed display preferences survive reboot', replay=replay)
        else:
            require(self.display.load_saved('vault') is None, 'Vault display preferences survived a new private session.')
            require(not self.inputs.PREFS.exists() and not self.inputs.LAYOUT.exists() and not self.pointer.PREFS.exists(),
                    'Vault input preference files survived reboot.')
            require(self.inputs.load() == self.inputs.DEFAULTS, 'Vault input defaults were not restored.')
            require(not Path('/run/core-vault-time/zone').exists(), 'Vault timezone state survived reboot.')
            mount = command(['/usr/bin/findmnt','--mountpoint','/etc/localtime'], check=False)
            require(mount.returncode != 0, 'A timezone bind mount unexpectedly survived reboot.')
            require(digest('/etc/localtime') == previous['time']['original_localtime_sha256'],
                    'Vault did not restore the image timezone after reboot.')
            self.passed('Vault input, display and timezone preferences reset after reboot')
        self.profiles.read(self.export_path,self.args.product)
        self.passed('Explicit USB device export remains valid after reboot', sha256=previous['export_sha256'])

    def vault_system_configuration(self):
        evidence = {}
        for value in ('/etc/default/keyboard', '/etc/X11/xorg.conf.d/00-keyboard.conf'):
            path = Path(value)
            try:
                info = path.stat()
            except FileNotFoundError:
                evidence[value] = dict(present=False)
                continue
            require(stat.S_ISREG(info.st_mode), 'Unexpected system keyboard configuration type: '+value)
            item = dict(present=True, uid=info.st_uid, gid=info.st_gid,
                        mode=oct(stat.S_IMODE(info.st_mode)), device=info.st_dev,
                        inode=info.st_ino, bytes=info.st_size,
                        mtime_ns=info.st_mtime_ns, ctime_ns=info.st_ctime_ns)
            try:
                item['sha256'] = digest(path)
                item['content_read'] = 'succeeded'
            except PermissionError:
                # Calamares creates this root-owned file with mode 0600.
                # Metadata evidence must not be described as a content hash.
                require(value == '/etc/X11/xorg.conf.d/00-keyboard.conf'
                        and info.st_uid == 0 and not info.st_mode & 0o022
                        and not os.access(path, os.W_OK),
                        'Unexpected unreadable or writable system keyboard configuration: '+value)
                item['content_read'] = 'permission-denied'
            evidence[value] = item
        return evidence

    def run(self):
        self.context()
        previous = json.loads(self.state_path.read_text()) if self.args.phase == 'reboot' else None
        self.iso(previous); self.runtime(previous)
        if previous is not None:
            self.reboot_checks(previous)
        self.gui()
        if self.args.phase == 'initial':
            original_keyboard = self.vault_system_configuration() if self.args.product == 'vault' else None
            if original_keyboard is not None:
                self.report['system_configuration_before'] = original_keyboard
                if any(item.get('content_read') == 'permission-denied' for item in original_keyboard.values()):
                    self.report['limitations'].append(
                        'The normal Vault user cannot read the protected Calamares keyboard configuration. '
                        'This run compares its observed identity, permissions, size and timestamps; '
                        'unchanged metadata is not proof of unchanged unreadable contents.')
                self.checkpoint()
            self.exercise_display(); exported = self.exercise_profiles()
            time_record = self.vault_time() if self.args.product == 'vault' else None
            if self.args.product == 'vault':
                current = self.vault_system_configuration()
                self.report['system_configuration_after'] = current
                require(current == original_keyboard, 'Vault input controls changed observed persistent system keyboard configuration.')
                importlib.import_module('vault_input_guard').require_ram_home()
                self.passed('Vault input leaves readable system content and observed metadata unchanged; home remains RAM',
                            system_configuration=current)
            state = dict(boot_id=self.report['boot_id'], iso=self.report['iso'],
                         runtime_sha256=self.report['runtime_sha256'],
                         protected_runtime_files=self.report['protected_runtime_files'],
                         export_sha256=digest(self.export_path), input_preferences=self.inputs.load(),
                         display_profile=self.display.load_saved(self.args.product), time=time_record)
            write_json(self.state_path, state)
        self.report['status'] = 'passed'
        self.checkpoint()

    def cleanup(self):
        if self.app is None:
            return
        from PySide6.QtCore import QThread, QTimer
        if self.display_dialog is not None and self.display_dialog.job is not None:
            self.display_dialog.job.decide('revert')
            try:
                self.wait(lambda:self.display_dialog.job is None,seconds=25,description='rollback cleanup')
            except Exception:
                pass
        windows = list(self.app.topLevelWidgets())
        threads = []
        for window in windows:
            for timer in window.findChildren(QTimer):
                timer.stop()
            threads.extend(window.findChildren(QThread))
            if window is not self.home:
                window.close()
        if self.home is not None:
            self.home.hide()
        def running(thread):
            try:
                return thread.isRunning()
            except RuntimeError:
                return False  # Qt already deleted a completed worker.
        deadline=time.monotonic()+20
        while time.monotonic()<deadline and any(running(thread) for thread in threads):
            self.app.processEvents();time.sleep(.025)
        self.app.processEvents()
        if any(running(thread) for thread in threads):
            self.report.update(status='failed', cleanup_error='A real Settings worker did not finish during guest cleanup.')
            self.checkpoint()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--media',required=True)
    parser.add_argument('--product',required=True,choices=('node','vault'))
    parser.add_argument('--phase',required=True,choices=('initial','reboot'))
    parser.add_argument('--run-id',required=True)
    parser.add_argument('--iso-sha256',required=True)
    parser.add_argument('--iso-bytes',required=True,type=int)
    parser.add_argument('--iso-device',default='/dev/sr0')
    args=parser.parse_args()
    require(re.fullmatch('[A-Za-z0-9_-]{1,40}',args.run_id),'Invalid test run ID.')
    require(re.fullmatch('[a-f0-9]{64}',args.iso_sha256),'Exact lowercase ISO SHA256 is required.')
    require(0<args.iso_bytes<=16*1024**3,'Invalid expected ISO size.')
    probe=Probe(args)
    try:
        probe.run()
    except Exception:
        probe.report.update(status='failed',error=traceback.format_exc())
        # Do not write to an unverified host path if context checks failed early.
        if 'guest' in probe.report:
            probe.checkpoint()
        print(probe.report['error'],file=sys.stderr,flush=True)
    finally:
        probe.cleanup()
    if probe.report['status'] == 'passed':
        print('SETTINGS_GUEST_PASSED '+args.product+' '+args.phase,flush=True)
        return 0
    return 1


if __name__=='__main__':
    raise SystemExit(main())
