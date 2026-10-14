# ADR-001 — Caddy как единый edge/TLS-терминация фермы

- **Статус:** принято (зафиксировано по фактическому состоянию 2026-10-14; реализовано ~2026-09)
- **Контекст:** на oc-node1 несколько веб-сервисов (Nextcloud, OpenClaw Control UI, BAS-IP Monitor),
  три публичных домена (cloud.paylama.tech, oc.paylama.tech, paylama.online); внутренние порты
  (OpenClaw Gateway 18789) наружу отдавать нельзя.
- **Решение:** единый Caddy в Docker (`/srv/caddy`, сеть `edge`, статический IP 172.18.0.10) терминирует
  TLS (HTTP/3), выдаёт HSTS/security-headers и делает reverse_proxy к сервисам; каждый сервис — свой
  site-блок в одном `Caddyfile`. Внутренние сервисы закрыты от Internet (доступ только через Caddy);
  `/metrics` на paylama.online отдаёт 404 (не светить метрики инвентаризации).
- **Последствия:** единая точка TLS/headers и простая добавка доменов; Caddy — единственный публичный
  entrypoint (порты 80/443) → жёсткая точка контроля. Минус: edge — SPOF для всех веб-сервисов.

Связи[ADR-001]: relates=oc-node1