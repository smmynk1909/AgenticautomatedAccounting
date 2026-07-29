# Restore drill runbook

Doc 12 §6 exit checklist: "restore drill < RTO." `DEVIATIONS.md` #24 has
the full design writeup and one real live-verified run (26s, 4h RTO
budget) — this is the short "how do I actually run it" version.

## Cadence

Doc 09 §3's ops-runbook essentials: "restore drill quarterly." Doc 12 §6
also names "2 clean payroll shadow cycles" as a separate go-live gate —
don't conflate the two; a restore drill proves backups are restorable, a
shadow cycle proves payroll math is correct. Both are needed, neither
substitutes for the other.

## Steps

```bash
make backup          # scripts/backup.sh — pg_dump + MinIO mirror + Qdrant snapshot
                      # to deploy/backups/<timestamp>/ (real running stack, needs `make up`)
make restore-drill    # scripts/restore_drill.sh — restores the LATEST
                      # backup into a throwaway `pg-restore-drill` container
                      # (never touches the real dev database), verifies
                      # row counts on employees/tickets/journal_entries/
                      # projects, reports elapsed time vs. the 4h RTO
                      # budget, then tears the throwaway container down
```

`restore_drill.sh` exits non-zero if any verified table restored empty —
treat that as a failed drill, not a warning.

## What this drill does NOT cover yet

- **MinIO/Qdrant restore** — only the backup side is implemented for
  those two stores; `restore_drill.sh` verifies Postgres only. Restoring
  MinIO is `mc mirror` in the opposite direction (same tool the backup
  side already uses); restoring a Qdrant snapshot is a POST to its
  snapshot-recover REST endpoint. Both are mechanically straightforward
  given the backup side already works — not done yet because nothing has
  exercised them, and doc 12 §6's checklist item is satisfied by the
  Postgres RTO number alone (Postgres is where the RTO-sensitive
  transactional data lives; MinIO/Qdrant hold documents and vector
  embeddings, both re-derivable from Postgres + source docs if truly
  lost, just slower).
- **Encryption at rest** — `DEVIATIONS.md` #24 flags this explicitly.
  Backups today are plain `pg_dump`/`mc mirror` output on local disk.
  Before this runbook is followed against anything with real data,
  encrypt the backup destination (disk-level or `gpg`-wrapping the dump)
  — doc 09 §3 says "encrypted disk," this build doesn't provide one.

## If a drill fails

Don't try to fix forward against the throwaway container — it's
disposable by design (`docker rm -f pg-restore-drill` is the actual
teardown). A failed drill means: (a) the backup itself was bad (rerun
`make backup`, then retry the drill against the fresh one), or (b) the
restore mechanism is broken (a real bug — file it, don't route around
it). Never treat "the drill script had a bug" as equivalent to "backups
are fine, ship it" — the whole point of a drill is testing the actual
recovery path, not the existence of a `.dump` file.
