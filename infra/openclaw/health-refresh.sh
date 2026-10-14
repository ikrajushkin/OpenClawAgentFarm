#!/bin/bash
# Refresh OpenClaw health metrics for Zabbix (OPF-6). Run by cron every 10 min as root.
# Server path: /usr/local/bin/openclaw-health-refresh.sh
mkdir -p /var/lib/openclaw-metrics
GA=0
systemctl is-active -q openclaw-gateway && GA=1
runuser -u openclaw -- env HOME=/srv/openclaw timeout 60 /usr/local/bin/openclaw cron list --json > /var/lib/openclaw-metrics/cron.json.tmp 2>/dev/null && mv /var/lib/openclaw-metrics/cron.json.tmp /var/lib/openclaw-metrics/cron.json
if [ -s /var/lib/openclaw-metrics/cron.json ]; then
  jq --argjson ga "$GA" '{gatewayActive:$ga, cronJobs:(.jobs|length), cronErrors:([.jobs[]? | select((.lastRunStatus // "") == "error")]|length), heartbeat:([.jobs[]? | select((.name // "") | test("heartbeat")) | {key:.agentId, value:(.lastRunStatus // "unknown")}] | from_entries)}' /var/lib/openclaw-metrics/cron.json > /var/lib/openclaw-metrics/health.json
else
  printf '{"gatewayActive":%s,"cronJobs":-1,"cronErrors":-1,"heartbeat":{}}\n' "$GA" > /var/lib/openclaw-metrics/health.json
fi
chmod 644 /var/lib/openclaw-metrics/health.json 2>/dev/null || true