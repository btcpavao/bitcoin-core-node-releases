# Login-only password for the managed Node desktop

Based on the accepted USB Read/Write runtime bd2be81. The old polkit rule
changed Node administration/login actions to AUTH_SELF whenever a login
password was enabled. That caused backup, restore and package actions to ask
for the same credential again. The rule no longer depends on login mode.

Only the active local `node` subject may invoke the four exact Node actions,
with the corresponding root-owned helper executable and root target identity.
Other users, remote sessions, inactive sessions, wrong helpers and wrong target
identities are refused. Other action IDs are not granted. The action XML fails
closed when the local rule is absent. No generic passwordless sudo, root shell,
policykit wildcard, agent removal, PAM change or wallet/GPG password bypass is
installed. Helper input validation, conflict locks, confirmations, package
verification and signature checks are unchanged.

Login still requires the configured password after startup/restart. Changing
or removing that login setting is an explicit action of the unlocked local
Node desktop and no longer requires re-entering the old password. The UI still
confirms password removal. An unattended unlocked desktop is therefore trusted
for the same fixed Node controls, including changing login settings. This is
an intentional single-user appliance policy, not a multi-user workstation policy.
Arbitrary commands typed in a terminal retain normal Linux sudo authentication.
Backup/GPG/wallet passphrases are separate and unchanged.

Native, HTML and plain-text Guide copies document the new behavior. Historical
acceptance records describe the earlier authorization model and are not rewritten.
Tests must verify both the intended allow cases and rejection boundaries, with
a login password actually enabled and no authentication agent available. The
physical user's login password/hash is never inspected or changed by testing.

## Automatic Private Workspace after decryption

After `decrypt_ui` completes authentication and atomic recovery publication,
it closes progress and opens the Private Workspace root in Thunar. It does not
show an additional modal success confirmation or launch any recovered file.
Wrong passphrases, cancelled operations and backend errors never trigger the
file-manager step. Recovery remains RAM-only with its original validations.

The workspace and final directory are checked before opening. If Thunar cannot
start or returns an error, a fallback message confirms that recovery succeeded
and gives the location; it does not delete or retry decryption. A running Thunar
window is not killed after the bounded startup check. Cryptographic passphrases
remain required for encrypted files, independently of the login-only change.
