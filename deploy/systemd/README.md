# Miru production backup timer

These units add a host-level, persistent daily verification of the application's
local SQLite backup. The application already performs an idempotent backup check
every six hours; the timer provides an independent host scheduler and catches
container or application scheduling failures.

The service runs the bounded `backup_admin.py create` command inside the active
production container. That command creates at most one daily and one ISO-weekly
snapshot for the period, verifies SQLite integrity and the attachment manifest,
and exits non-zero on failure. Output is aggregate metadata only.

`miru-backup-failure@.service` writes only the fixed journald marker
`MIRU_BACKUP_ALERT=backup_failed`. It does not send data to a third party. A later
off-host/notification integration may consume that marker after separate user
authorization.

## Controlled installation

Installation is a privileged production change and must be explicitly approved.
Copy all three unit files to `/etc/systemd/system/`, run `systemctl daemon-reload`,
start `miru-backup.service` once, inspect its bounded output, and only then enable
`miru-backup.timer` with `--now`.

Verification commands:

```sh
systemd-analyze verify /etc/systemd/system/miru-backup.service \
  /etc/systemd/system/miru-backup.timer \
  /etc/systemd/system/miru-backup-failure@.service
systemctl is-enabled miru-backup.timer
systemctl is-active miru-backup.timer
systemctl list-timers miru-backup.timer --no-pager
journalctl -u miru-backup.service -n 20 --no-pager
```

The timer can be disabled without deleting any backup data:

```sh
sudo systemctl disable --now miru-backup.timer
```
