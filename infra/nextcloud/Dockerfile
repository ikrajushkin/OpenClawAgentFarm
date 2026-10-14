FROM nextcloud:34-apache
# gid 2000 = группа shared на хосте. Нужна ИМЕННО в /etc/group контейнера:
# Apache при старте воркеров делает initgroups() и берёт группы отсюда,
# а не из docker group_add. Без этого воркеры теряют доступ к /mnt/shared.
RUN groupadd -g 2000 shared && usermod -aG shared www-data
