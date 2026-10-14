#!/bin/bash
# oc-backup.sh - regular backup of oc-node1 data (OPF-4).
# Server path: /usr/local/bin/oc-backup.sh (repo copy: infra/backup/oc-backup.sh in OpenClawFarm).
# Run daily by cron as root (/etc/cron.d/oc-backup). Artifacts -> /srv/openclaw/backups/auto/<stamp>/.
# Contents: pg dumps (nc-db, basip), /srv/shared, /srv/openclaw/.openclaw state,
# /srv/nextcloud/html, basip secrets, basip git bundle. Retention: KEEP newest run dirs.
# Metrics for Zabbix: /var/lib/openclaw-metrics/backup.json (key custom.openclaw.backup.*).
set -uo pipefail

BACKUP_ROOT=/srv/openclaw/backups/auto
METRICS=/var/lib/openclaw-metrics/backup.json
LOG=/var/log/oc-backup.log
KEEP=5
STAMP=$(date +%Y%m%d-%H%M%S)
DEST="$BACKUP_ROOT/$STAMP"
FAILED=0

log() { echo "$(date -Is) $*" | tee -a "$LOG"; }

mkdir -p "$DEST" "$(dirname "$METRICS")"
log "=== backup start $STAMP ==="

# --- PostgreSQL dumps (custom format, compressed internally) ---
dump_pg() {
  local cname=$1 dbuser=$2 db=$3 out="$DEST/$4"
  if docker exec "$cname" pg_dump -U "$dbuser" -Fc "$db" > "$out" 2>>"$LOG"; then
    log "OK   pg_dump $cname.$db -> $(du -h "$out" | cut -f1)"
  else
    rm -f "$out"
    log "FAIL pg_dump $cname.$db"
    FAILED=1
  fi
}
dump_pg nc-db nextcloud nextcloud nextcloud-db.dump
dump_pg basip-monitor-postgres-1 basip basip basip-db.dump

# --- tar.zst archives ---
archive() {
  local name=$1; shift
  if tar --warning=no-file-changed -I 'zstd -T0 -6' -cf "$DEST/$name" "$@" 2>>"$LOG"; then
    log "OK   archive $name -> $(du -h "$DEST/$name" | cut -f1)"
  else
    rm -f "$DEST/$name"
    log "FAIL archive $name"
    FAILED=1
  fi
}
# shared work zone (ADR-003): Docs, Inbox, Media, Outbox, Projects, Workspace, captures
archive shared.tar.zst -C /srv shared
# openclaw state: config, agents, credentials, extensions, media, tools, state (cache/tmp/logs/npm are regenerable)
archive openclaw-state.tar.zst -C /srv/openclaw \
  --exclude='.openclaw/cache' --exclude='.openclaw/tmp' --exclude='.openclaw/logs' --exclude='.openclaw/npm' \
  .openclaw
# nextcloud user files + config.php
archive nextcloud-html.tar.zst -C /srv/nextcloud html
# basip secrets (master.key, syslog.key) - stays on-server, treated as secret
archive basip-secrets.tar.zst -C /srv/projects/bas-ip-monitor secrets

# --- basip git bundle (all refs) ---
if git -C /srv/projects/bas-ip-monitor -c safe.directory=/srv/projects/bas-ip-monitor \
     bundle create "$DEST/basip-git.bundle" --all >>"$LOG" 2>&1; then
  log "OK   basip-git.bundle -> $(du -h "$DEST/basip-git.bundle" | cut -f1)"
else
  rm -f "$DEST/basip-git.bundle"
  log "FAIL basip-git.bundle"
  FAILED=1
fi

# --- manifest + metrics ---
SIZE=$(du -sb "$DEST" | cut -f1)
(cd "$DEST" && sha256sum -- * > SHA256SUMS 2>>"$LOG") || log "WARN SHA256SUMS not written"

LAST_OK_EPOCH=0
[ -f "$BACKUP_ROOT/LAST_OK" ] && LAST_OK_EPOCH=$(stat -c %Y "$BACKUP_ROOT/LAST_OK")
if [ "$FAILED" -eq 0 ]; then
  touch "$BACKUP_ROOT/LAST_OK"
  LAST_OK_EPOCH=$(date +%s)
  STATUS=ok
else
  STATUS=error
fi
jq -n --arg stamp "$STAMP" --arg status "$STATUS" \
      --argjson lastOkEpoch "$LAST_OK_EPOCH" --argjson sizeMb "$((SIZE / 1024 / 1024))" \
      '{stamp:$stamp, status:$status, lastOkEpoch:$lastOkEpoch, sizeMb:$sizeMb}' > "$METRICS"
chmod 644 "$METRICS"

# --- retention: keep newest $KEEP run dirs ---
ls -1dt "$BACKUP_ROOT"/*/ 2>/dev/null | tail -n +$((KEEP + 1)) | while read -r old; do
  log "drop old backup $old"
  rm -rf "$old"
done

log "=== backup end status=$STATUS sizeMb=$((SIZE / 1024 / 1024)) ==="
[ "$FAILED" -eq 0 ]