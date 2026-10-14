# infra/ — выгрузка конфигураций oc-node1

Побайтовая выгрузка non-secret-конфигов с сервера **45.91.237.204** от **2026-10-14** (секреты заменены
на `***MASKED***`). Назначение и порядок применения — [`../docs/Восстановление-и-развёртывание.md`](../docs/Восстановление-и-развёртывание.md).

Правила:
- **Секреты сюда не копировать** (токены, пароли, ключи) — только маски и ссылки на места хранения.
- При изменении конфига на сервере — перегружать файл сюда и обновлять дату сверки в доках (OPF-4).
- Файлы `*.example` — шаблоны: реальные значения подставляются при развёртывании.

Эксплуатационные артефакты (добавлено 2026-10-14):
- `openclaw/usage-refresh.sh` — cron-сбор usage-метрик в `/var/lib/openclaw-metrics/usage.json`
  (на сервере: `/usr/local/bin/openclaw-usage-refresh.sh`, вызов от root через `runuser -u openclaw`);
- `zabbix/openclaw-usage.conf` — UserParameter `custom.openclaw.usage.{cost,tokens,input,output,cache_read}`
  (на сервере: `/etc/zabbix/zabbix_agentd.d/openclaw.conf`);
- `cron/openclaw-metrics` — `/etc/cron.d/openclaw-metrics`, запуск refresh каждые 10 минут;
- `openclaw/health-refresh.sh` — сбор health-метрик (gateway/cron/heartbeats) в
  `/var/lib/openclaw-metrics/health.json` (на сервере: `/usr/local/bin/openclaw-health-refresh.sh`);
- `zabbix/openclaw-health.conf` — UserParameter `custom.openclaw.gateway.active`,
  `custom.openclaw.cron.{jobs,errors}`, `custom.openclaw.heartbeat.{main,ksu,service}`;
- `zabbix/openclaw-triggers.md` — спецификация элементов данных и триггеров для Zabbix-сервера (OPF-6).

Бэкапы и restore (добавлено 2026-10-14, OPF-4):
- `backup/oc-backup.sh` — ежедневный бэкап (pg-дампы nc-db/basip, `/srv/shared`, `.openclaw`,
  `nextcloud/html`, basip-secrets, git-bundle basip, SHA256SUMS; ротация 5 прогонов)
  (на сервере: `/usr/local/bin/oc-backup.sh`, артефакты `/srv/openclaw/backups/auto/<штамп>/`);
- `backup/oc-restore-test.sh` — еженедельная restore-дрель (sha256, tar -t, реальный pg_restore
  обоих дампов во временные контейнеры) (на сервере: `/usr/local/bin/oc-restore-test.sh`);
- `cron/oc-backup` — `/etc/cron.d/oc-backup`: бэкап 03:30 ежедневно, restore-дрель вс 04:30;
- `zabbix/openclaw-backup.conf` — UserParameter `custom.openclaw.backup.{status,age_hours,sizeMb}`,
  `custom.openclaw.restore.status`;
- `versions/ai-stack-versions.md` — пины whisper.cpp (git-commit), Piper 1.2.0 (md5 голоса),
  Parakeet (ONNX-модель + freeze venv).