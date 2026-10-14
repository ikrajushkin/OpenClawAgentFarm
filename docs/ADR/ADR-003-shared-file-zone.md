# ADR-003 — Общая файловая зона `/srv/shared` (group `shared`, UMask 0002)

- **Статус:** принято (зафиксировано по фактическим конфигам 2026-10-14; реализовано ~2026-09)
- **Контекст:** OpenClaw-агент и Nextcloud работают под разными пользователями, но должны обмениваться
  файлами (Workspace/Inbox/Outbox, документы, захваты медиа). Точка обмена — `/srv/shared/{Workspace,Inbox,Outbox,Docs,Projects,Media,captures}`.
- **Решение:** директории `/srv/shared` — group `shared` + setgid, а у `openclaw-gateway.service`
  `UMask=0002` **обязателен** (комментарий в юните: файлы должны быть group-writable для Nextcloud);
  сервис входит в `SupplementaryGroups=shared`. Nextcloud монтирует/читает эту зону со своей стороны.
- **Последствия:** совместная запись без chmod-костылей; любой новый компонент, работающий с shared-зоной,
  обязан наследовать UMask 0002 / группу `shared`, иначе появляются «немые» файлы без прав на запись.

Связи[ADR-003]: relates=ADR-001,ADR-002