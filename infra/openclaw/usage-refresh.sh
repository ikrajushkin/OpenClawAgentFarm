#!/bin/bash
# Refresh OpenClaw usage metrics for Zabbix (OPF-6). Run by cron every 10 min as root.
# Server path: /usr/local/bin/openclaw-usage-refresh.sh
mkdir -p /var/lib/openclaw-metrics
runuser -u openclaw -- env HOME=/srv/openclaw timeout 60 /usr/local/bin/openclaw gateway usage-cost --json --all-agents --days 1 > /var/lib/openclaw-metrics/usage.json.tmp 2>/dev/null && mv /var/lib/openclaw-metrics/usage.json.tmp /var/lib/openclaw-metrics/usage.json
chmod 644 /var/lib/openclaw-metrics/usage.json 2>/dev/null || true