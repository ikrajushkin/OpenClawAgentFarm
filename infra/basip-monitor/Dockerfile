# Стек зафиксирован в ENGINEERING §2: Python 3.12.
# Версия закреплена явно — «latest» однажды меняет мажор и ломает сборку
# в самый неподходящий момент.
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# ffmpeg нужен проверке video (блок 5): ffprobe вызывается как внешний
# процесс, развилка 1A. Ставим на уровне образа, чтобы проверка не
# зависела от того, что оказалось на хосте.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./

# Процесс не от root: у контейнера нет причин иметь лишние права.
#
# Каталог под архивы создаётся ЗДЕСЬ и с правильным владельцем:
# docker инициализирует новый именованный том содержимым образа
# и переносит владельца. Без этого том создаётся от root, а запись
# падает с Permission denied — проверено на живом стеке 08.09.2026.
#
# Последствие было бы тихим и опасным: архив не сохраняется, значит
# очистка навсегда запрещена правилом, и логи на панелях росли бы
# до паралича, а система сообщала бы `unknown`, а не отказ.
RUN useradd --create-home --uid 10001 basip \
 && mkdir -p /var/lib/basip/archives \
 && chown -R basip:basip /app /var/lib/basip
USER basip

EXPOSE 8000

# Проверка живости внутри контейнера — /healthz, а не /readyz:
# недоступная БД не повод перезапускать процесс, перезапуск её не чинит.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]


# Отдельная ступень для тестов. Собирается только явно
# (--target test), поэтому pytest и прочая обвязка не попадают в
# рабочий образ. Лишние пакеты в продакшене — это лишняя
# поверхность атаки и лишние обновления безопасности.
FROM runtime AS test

USER root
COPY backend/requirements-dev.txt ./requirements-dev.txt
RUN pip install --no-cache-dir -r requirements-dev.txt
USER basip

CMD ["python", "-m", "pytest", "-q"]
