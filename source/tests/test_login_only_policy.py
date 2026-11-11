"""Execute the real polkit JavaScript against strict session/action boundaries."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
RULE = ROOT / 'runtime/etc/polkit-1/rules.d/49-core-node.rules'
ACTIONS = {f'org.bitcoin-core-node.{kind}': f'/usr/libexec/core-node-{kind}'
           for kind in ('admin', 'login', 'power', 'service')}
JS = r'''
const fs=require('fs'),vm=require('vm');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
let rule;
const context={polkit:{Result:{YES:'yes',NO:'no'},
 addRule:fn=>{if(rule)throw Error('extra rule');rule=fn;},
 spawn:()=>{throw Error('Login-only policy must not probe password mode');}}};
vm.runInNewContext(fs.readFileSync(input.rule,'utf8'),context,{timeout:1000});
if(!rule)throw Error('missing rule');
const out=input.cases.map(c=>rule({id:c.id,lookup:k=>c.details[k]},c.subject));
console.log(JSON.stringify(out.map(v=>v===undefined?'unhandled':v)));
'''

class LoginOnlyPolicy(unittest.TestCase):
    def run_cases(self, cases):
        node=shutil.which('node') or shutil.which('nodejs')
        self.assertIsNotNone(node,'Node.js is required to execute the polkit rule tests')
        result=subprocess.run([node,'-e',JS],input=json.dumps({'rule':str(RULE),'cases':cases}),
                              text=True,capture_output=True,timeout=10,check=True)
        return json.loads(result.stdout)

    def case(self, action, **subject):
        return {'id':action,'subject':dict(user='node',local=True,active=True,**subject),
                'details':{'program':ACTIONS[action],'user':'root'}}

    def test_active_local_desktop_allowed_without_password_mode_probe(self):
        cases=[self.case(a) for a in ACTIONS]
        self.assertEqual(self.run_cases(cases),['yes']*4)
        text=RULE.read_text()
        self.assertNotIn('AUTH_SELF',text)
        self.assertNotIn('passwordless-status',text)
        self.assertNotIn('polkit.spawn',text)

    def test_other_users_inactive_remote_and_invalid_flags_are_denied(self):
        cases=[]
        for action in ACTIONS:
            for change in ({'user':'bitcoinnode'},{'user':'node-live'},{'user':'root'},
                           {'user':'someone'},{'local':False},{'active':False},
                           {'active':'true'},{'local':1},{'active':None}):
                c=self.case(action);c['subject'].update(change);cases.append(c)
        self.assertEqual(self.run_cases(cases),['no']*len(cases))

    def test_exact_helper_and_root_target_required(self):
        cases=[]
        for action in ACTIONS:
            for details in ({'program':'/usr/bin/bash'}, {'program':ACTIONS[action]+'-evil'},
                            {'program':'/usr/bin/python3'}, {'user':'node'},
                            {'program':None},{'user':None}):
                c=self.case(action);c['details'].update(details);cases.append(c)
        self.assertEqual(self.run_cases(cases),['no']*len(cases))

    def test_unrelated_and_prototype_actions_are_not_granted(self):
        cases=[]
        for action in ('org.freedesktop.policykit.exec','org.freedesktop.systemd1.manage-units',
                       'org.bitcoin-core-node.admin.evil','org.bitcoin-core-node.anything',
                       'toString','constructor','__proto__'):
            c=self.case(next(iter(ACTIONS)));c['id']=action;cases.append(c)
        self.assertEqual(self.run_cases(cases),['unhandled']*len(cases))

    def test_policy_files_fail_closed_and_match_exact_executables(self):
        for action,path in ACTIONS.items():
            document=ET.parse(ROOT/f'runtime/usr/share/polkit-1/actions/{action}.policy')
            records=document.findall('action');self.assertEqual(len(records),1)
            entry=records[0];self.assertEqual(entry.attrib['id'],action)
            for tag in ('allow_any','allow_inactive','allow_active'):
                self.assertEqual(entry.findtext('defaults/'+tag),'no')
            values={a.attrib['key']:a.text for a in entry.findall('annotate')}
            self.assertEqual(values,{'org.freedesktop.policykit.exec.path':path})

    def test_no_generic_sudo_change_and_current_guide_consistent(self):
        self.assertFalse((ROOT/'runtime/etc/sudoers').exists())
        self.assertFalse((ROOT/'runtime/etc/sudoers.d').exists())
        for relative in ('app/guide_ui.py','runtime/usr/share/bitcoin-core-node/GUIDE.html',
                         'runtime/usr/share/bitcoin-core-node/GUIDE.txt'):
            s=(ROOT/relative).read_text()
            self.assertIn('not to authorize each Node action',s)
            self.assertIn('wallet encryption remain separate',s)
            self.assertNotIn('Changing or removing an existing password asks for the current password',s)
        ui=(ROOT/'app/login_ui.py').read_text()
        self.assertNotIn('please enter the current login password',ui)
        self.assertIn('QMessageBox',ui)  # Explicit remove confirmation remains.

if __name__=='__main__':unittest.main()
