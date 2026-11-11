"""Validate all input before privileged clock changes."""
from datetime import datetime, timezone
from pathlib import Path
import subprocess, sys, unittest
from unittest.mock import call, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import system_time as t
STATE = dict(timezone='UTC', automatic=True, synchronized=False, can_automatic=True)

class SystemTime(unittest.TestCase):
 def test_manual_zone_converts_to_absolute_time(self):
  name,automatic,epoch=t.validate_request(dict(timezone='Europe/Zagreb',automatic=False,local_time='2026-10-30 14:35:00'))
  self.assertEqual((name,automatic),('Europe/Zagreb',False))
  self.assertEqual(datetime.fromtimestamp(epoch,timezone.utc),datetime(2026,10,30,13,35,tzinfo=timezone.utc))
 def test_dst_gap_and_fold_are_refused(self):
  for value in ('2026-03-29 02:30:00','2026-10-25 02:30:00'):
   with self.assertRaises(t.TimeError):t.validate_request(dict(timezone='Europe/Zagreb',automatic=False,local_time=value))
 def test_invalid_requests_have_no_side_effects(self):
  invalid=[None,[],{},dict(timezone='UTC',automatic=1),dict(timezone='UTC',automatic=True,local_time='now'),dict(timezone='UTC',automatic=False),dict(timezone='UTC',automatic=False,local_time='yesterday'),dict(timezone='UTC',automatic=False,local_time='2026-02-30 12:00:00'),dict(timezone='UTC',automatic=False,local_time='1900-01-01 00:00:00')]
  invalid += [dict(timezone=value,automatic=True) for value in ('../../etc/passwd','/etc/localtime','UTC\n--help','UTC; touch /tmp/no','--help','right/UTC','posix/UTC','localtime','zone.tab','Missing/Zone')]
  with patch.object(t,'runctl') as run:
   for request in invalid:
    with self.subTest(request=request),self.assertRaises(t.TimeError):t.apply_settings(request)
   run.assert_not_called()
 def test_automatic_only_changes_zone_and_service(self):
  with patch.object(t,'snapshot',return_value=STATE),patch.object(t,'runctl') as run:
   self.assertTrue(t.apply_settings(dict(timezone='Europe/Zagreb',automatic=True))['ok'])
   self.assertEqual(run.call_args_list,[call('set-timezone','Europe/Zagreb'),call('set-ntp','true')])
 def test_manual_disables_ntp_before_absolute_time(self):
  request=dict(timezone='UTC',automatic=False,local_time='2026-10-30 12:00:00');epoch=t.validate_request(request)[2]
  with patch.object(t,'snapshot',return_value=STATE),patch.object(t,'runctl') as run:
   t.apply_settings(request)
   self.assertEqual(run.call_args_list,[call('set-ntp','false'),call('set-timezone','UTC'),call('set-time','@'+str(epoch))])
 def test_service_missing_and_command_failure_are_actionable(self):
  with patch.object(t,'snapshot',return_value=dict(STATE,can_automatic=False)),patch.object(t,'runctl') as run:
   with self.assertRaisesRegex(t.TimeError,'unavailable'):t.apply_settings(dict(timezone='UTC',automatic=True))
   run.assert_not_called()
  with patch.object(t,'snapshot',return_value=STATE),patch.object(t,'runctl',side_effect=subprocess.TimeoutExpired('timedatectl',15)):
   with self.assertRaisesRegex(t.TimeError,'Some settings may have changed'):t.apply_settings(dict(timezone='UTC',automatic=True))
 def test_status_is_read_only_and_validated(self):
  with patch.object(t,'runctl',return_value='Timezone=UTC\nNTP=yes\nNTPSynchronized=no\nCanNTP=yes\n') as run:
   self.assertEqual(t.snapshot(),STATE);self.assertEqual(run.call_args.args[0],'show')
  with patch.object(t,'runctl',return_value='Timezone=UTC\nNTP=maybe\nNTPSynchronized=no\nCanNTP=yes\n'):
   with self.assertRaises(t.TimeError):t.snapshot()
if __name__=='__main__':unittest.main()
