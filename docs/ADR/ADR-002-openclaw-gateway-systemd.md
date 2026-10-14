# ADR-002 — OpenClaw Gateway как systemd-сервис на хосте, а не в Docker

- **Статус:** принято (зафиксировано по фактическому состоянию 2026-10-14; реализовано ~2026-09)
- **Контекст:** агенту OpenClaw нужен доступ к хостовым ресурсам: обмен с Nextcloud через `/srv/shared`,
  встроенный браузер, STT/TTS-инструменты в `/opt`, долгоживущее состояние в `/srv/openclaw`.
- **Решение:** Gateway запускается systemd-юнитом `openclaw-gateway.service` от сервисного пользователя
  `openclaw` (не root — иначе §1.2): `MemoryMax=6G`, `UMask=0002` (файлы group-writable для Nextcloud),
  `SupplementaryGroups=shared`, `ReadWritePaths=/srv/openclaw /srv/shared /tmp`. Сетевой доступ — только
  на 172.18.0.1:18789 (адрес хоста в docker-сети `edge`) и loopback; наружу — исключительно через Caddy
  ([ADR-001](ADR-001-caddy-edge-proxy.md)).
- **Последствия:** простой доступ к файлам и устройствам хоста, изоляция через systemd-hardening
  (NoNewPrivileges, ProtectSystem=full); не нужно docker-in-docker. Минус: агент не переносим контейнером,
  зависит от конфигурации хоста. Управление — только через обёртку `oc` (§1.2).

Связи[ADR-002]: depends-on=ADR-001