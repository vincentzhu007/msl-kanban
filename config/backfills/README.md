# Explicit, revocable package lock for the 1.5B backfill

The JSON file in this directory is an optional overlay, not a full task
configuration and not an active Daily default. Nothing loads this directory
automatically. Merge the object into the two approved 1.5B task configs only
when a deployment is separately authorized. Never replace a full config with it.

`package_lock` is a top-level task-config field. The existing config loader
accepts optional top-level fields. The recipe and environment keep their own
schemas. The pipeline checks the lock before it takes a device lease.

## Identity and run date

Package identity is the SHA256, the official `source_url`, and the build
commit. `day` inside the lock only records the date embedded in that URL.
The `20261123` path component is part of the artifact location. It is not the
calendar day a scheduled job may run, and it is not compared to `--date`.

The next scheduled run passes no `--date`. `scripts/daily.py` then uses the
Asia/Shanghai wall clock, which is `20261124` at 03:00 on that morning. A
config that contains this lock accepts that run date, and any other requested
day, when the cached file matches. Missing bytes or a SHA mismatch stop the
task. There is no listing discovery, download, newest-package fallback, or
cache repair.

The exact file must already be at
`<archive_root>/packages/<sha256>/mindspore-lite-llm-linux-x64-0.2.0.tar.gz`.
Selection and preparation each hash it locally. The directory stamp in the
URL is a build label, not proof of an archive-completion time. The run's own
`date` stays the requested day. The lock is also copied to `package-lock.json`.

## Revocation

After this backfill has been included in the formal scheduled run, delete the
entire top-level `package_lock` key from both private configs. Do not leave
null or an empty object. Absence restores `discover(day)` for the requested
run day. This change does not install the key, remove it, or alter cron,
matrix, or the scheduled command.

## Global fport snapshots

A targeted `hdc -t <serial> fport ls` can still list other serials. Port
choice keeps every parsed row, including ports owned by 3000, 3001, or another
serial. `editable_rows` contains only the target serial. Create and delete
touch only this session's own tuple. Unknown lines fail closed. The same host
port on two rows is not removed. A foreign row that replaces our tuple is not
deleted. Cleanup that cannot prove ownership leaves our forward in place.
There is no official `br push`, restart, force-stop, or fallback.
