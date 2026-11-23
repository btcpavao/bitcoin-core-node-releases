#!/usr/bin/python3
"""Diagnostic component checks after a preserved actual Display acceptance failure.

This does not replace settings_guest_probe.py and never reports full acceptance.
It leaves Display Apply untested, exercises real input/USB controls and the Vault
time helper, and preserves the original failed report. Only owned offline QEMU
sessions accepted by the ordinary guest probe are permitted.
"""
import argparse
import copy
from dataclasses import asdict
import json
import re
import sys
import traceback

from settings_guest_probe import Probe, command, digest, require


class Components(Probe):
    def input_and_usb(self):
        self.keyboard(650)
        self.display_dialog.back_button.click(); self.app.processEvents()
        self.display_dialog = None
        profiles = self.home.device_profiles('export'); self.app.processEvents()
        require(not self.export_path.exists(), 'Please use a fresh diagnostic run ID.')
        self.picker_click(profiles.export_button, self.export_path)
        require(self.export_path.is_file(), profiles.feedback.text())
        exported = self.profiles.read(self.export_path, self.args.product)
        require(exported['input']['preferences']['keyboard']['delay_ms'] == 650,
                'The actual USB export did not contain the saved keyboard preference.')
        require(exported['display'] is None,
                'This isolated diagnostic expects no confirmed display profile.')
        original_hash = digest(self.export_path)
        try:
            self.profiles.write(self.export_path, exported, self.args.product)
        except FileExistsError:
            pass
        else:
            raise RuntimeError('Export unexpectedly overwrote an existing file.')
        require(digest(self.export_path) == original_hash, 'Existing device profile bytes changed.')
        self.keyboard(750)
        self.picker_click(profiles.import_button, self.export_path)
        require(profiles.profile is not None and profiles.apply.isEnabled(), profiles.feedback.text())
        require(not profiles.displays.isEnabled(), 'An absent display profile must not be applicable.')
        profiles.apply.click()
        self.wait(lambda: profiles.job is None and profiles.feedback.text().startswith('Input preferences applied.'),
                  description='actual diagnostic input profile import')
        require(self.inputs.load()['keyboard']['delay_ms'] == 650,
                'The actual USB import did not restore the exported keyboard preference.')
        self.capture(profiles, 'input-only-profile')
        profiles.back.click(); self.app.processEvents()
        self.passed('Diagnostic: actual input-only USB export/import succeeds',
                    file=self.export_path.name, sha256=original_hash, keyboard_delay_ms=650)

    def run(self):
        self.context(); self.iso(); self.runtime()
        failed_path = self.media/self.args.display_failure_report
        failed = json.loads(failed_path.read_text())
        require(failed.get('status') == 'failed' and failed.get('product') == self.args.product
                and failed.get('iso', {}).get('sha256') == self.args.iso_sha256
                and 'complete display layout' in failed.get('error', ''),
                'A matching preserved actual Display failure is required for this diagnostic.')
        self.report.update(kind='bitcoin-core-settings-component-diagnostic-v1',
                           display_acceptance='failed-in-preserved-report',
                           preserved_failure=dict(file=failed_path.name, sha256=digest(failed_path)),
                           component_failures=[])
        self.report['limitations'].append(
            'Diagnostic only: Display Apply, Keep/Revert, timeout, display-profile import and reboot '
            'acceptance are not passed by this run. The preserved Display failure remains unresolved.')
        self.gui()
        before = self.backend.probe(transforms=True)
        requested = self.display.layout_from_snapshot(before, '1.25')
        output = before.active[0]
        choices = [m for m in output.modes if m.name != output.mode and m.width >= 800 and m.height >= 600]
        roomy = [m for m in choices if m.width >= 1000 and m.height >= 750]
        if choices:
            mode = min(roomy or choices, key=lambda m: abs(m.width-1024)+abs(m.height-768))
            requested = copy.deepcopy(requested)
            requested['outputs'][0].update(mode=mode.name, rate=mode.rates[0], rotation='normal')
        self.report['display_readback'] = dict(snapshot=asdict(before), requested=requested,
            command=self.display.command_for_layout(requested, before),
            query=command(['/usr/bin/xrandr', '--query', '--props']).stdout,
            verbose=command(['/usr/bin/xrandr', '--verbose']).stdout,
            applied_in_this_diagnostic=False)
        original = self.vault_system_configuration() if self.args.product == 'vault' else None
        if original is not None:
            self.report['system_configuration_before'] = original
            self.report['limitations'].append(
                'Protected keyboard configuration has metadata evidence only; unreadable contents are not hashed.')
        self.checkpoint()
        operations = [('Input and USB profiles', self.input_and_usb)]
        if self.args.product == 'vault':
            operations.append(('Manual clock and RAM timezone', self.vault_time))
        for name, operation in operations:
            try:
                result = operation()
                if name == 'Manual clock and RAM timezone':
                    self.report['time'] = result
            except Exception:
                failure = dict(component=name, error=traceback.format_exc())
                self.report['component_failures'].append(failure)
                print(json.dumps(failure), file=sys.stderr, flush=True)
            self.checkpoint()
        if original is not None:
            current = self.vault_system_configuration()
            self.report['system_configuration_after'] = current
            require(current == original, 'Observed persistent keyboard configuration changed.')
            __import__('vault_input_guard').require_ram_home()
            self.passed('Diagnostic: readable keyboard content and observed metadata unchanged; RAM home verified')
        require(digest(failed_path) == self.report['preserved_failure']['sha256'],
                'The earlier failed acceptance report changed.')
        self.report['status'] = 'component-diagnostic-failed' if self.report['component_failures'] else 'component-diagnostic-passed'
        self.checkpoint()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--media', required=True)
    parser.add_argument('--product', required=True, choices=('node', 'vault'))
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--iso-sha256', required=True)
    parser.add_argument('--iso-bytes', required=True, type=int)
    parser.add_argument('--iso-device', default='/dev/sr0')
    parser.add_argument('--display-failure-report', required=True)
    args = parser.parse_args(); args.phase = 'initial'
    require(re.fullmatch('[A-Za-z0-9_-]{1,40}', args.run_id), 'Invalid diagnostic run ID.')
    require(re.fullmatch('[a-f0-9]{64}', args.iso_sha256), 'Exact ISO SHA256 required.')
    require(0 < args.iso_bytes <= 16*1024**3, 'Invalid ISO size.')
    require(re.fullmatch('[A-Za-z0-9_-]+[.]json', args.display_failure_report), 'Invalid failure-report filename.')
    probe = Components(args)
    try:
        probe.run()
    except Exception:
        probe.report.update(status='component-diagnostic-failed', error=traceback.format_exc())
        if 'guest' in probe.report:
            probe.checkpoint()
        print(probe.report['error'], file=sys.stderr, flush=True)
    finally:
        probe.cleanup()
    print('SETTINGS_COMPONENT_DIAGNOSTIC '+probe.report['status'], flush=True)
    return 0 if probe.report['status'] == 'component-diagnostic-passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
