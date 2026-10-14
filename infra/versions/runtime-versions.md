# Версии рантаймов и ОС (снято 2026-10-14, oc-node1)

| Компонент | Версия |
|---|---|
| ОС | Ubuntu 26.04.1 LTS («Resolute Raccoon»), ядро 7.0.0-30-generic |
| OpenClaw CLI / Gateway | OpenClaw 2026.8.2 (0965053) |
| Node.js | v24.20.0 |
| Python | 3.14.4 (системный python3) |
| Ollama | 0.33.2 (модель `bge-m3`) |
| Docker Compose | v5.5.0 |
| Nextcloud | 34.0.3 (приложения: notify_push 1.4.0, office 1.0.0) |
| whisper.cpp | модель `ggml-medium-q5_0.bin` в `/opt/whisper-models` (сборка — см. OPF-4) |
| STT/TTS доп. | piper (+ `/opt/piper-voices`), parakeet — версии не зафиксированы (пробел OPF-4) |

Digest-ы Docker-образов — в [`docker-images-digests.txt`](docker-images-digests.txt)
(колонка `DIGEST` == image ID: RepoDigest для локально собранных образов не сохраняется).