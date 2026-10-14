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
| LLM (основная цепочка) | `polza-ds/deepseek/deepseek-v4.1-flash` + фолбэки `deepseek-v4-flash`, `-0731` (см. ADR-004) |
| STT (активный) | Parakeet `nemo-parakeet-tdt-0.6b-v3` (`/usr/local/bin/parakeet-cli`, ONNX `istupakov/parakeet-tdt-0.6b-v3-onnx`) |
| STT (резерв) | whisper.cpp: `ggml-medium-q5_0.bin` (активный в env) + base/small/medium в `/opt/whisper-models` |
| TTS (активный) | Microsoft neural `ru-RU-SvetlanaNeural` (ogg-24khz-16bit-mono-opus) |
| TTS (резерв/прошлое) | Piper `ru_RU-irina-medium` (`/opt/piper-voices`) |

Digest-ы Docker-образов — в [`docker-images-digests.txt`](docker-images-digests.txt)
(колонка `DIGEST` == image ID: RepoDigest для локально собранных образов не сохраняется).

Пины whisper.cpp / Piper / Parakeet (коммиты, md5 моделей, freeze venv) —
в [`ai-stack-versions.md`](ai-stack-versions.md).