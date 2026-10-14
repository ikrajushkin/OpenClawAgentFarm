# Пины AI/ML-стека: whisper.cpp, Piper, Parakeet (снято 2026-10-14, oc-node1)

> Закрывает пункт OPF-4 «пины сборок piper / parakeet / whisper.cpp». Контекст —
> [`../../docs/Восстановление-и-развёртывание.md`](../../docs/Восстановление-и-развёртывание.md) §3/§6.

## whisper.cpp (STT, резерв)

| Что | Значение |
|---|---|
| Исходники | `/opt/whisper.cpp`, git commit `eacbd8234c6654cdbf2c377f72b2106875479bdc` (2026-08-31) |
| Сборка | собственная (`make`), CLI `whisper-cli`; вызов из `/etc/openclaw/env` (`ggml-medium-q5_0`) |

Модели `/opt/whisper-models` (md5):

| Модель | md5 |
|---|---|
| `ggml-medium-q5_0.bin` (активная) | `3bb99a2f4c3b88d2645f878e6e39a8aa` |
| `ggml-medium.bin` | `84d6237ed581ac2ddbe616610f6de256` |
| `ggml-small-q5_1.bin` | `059a696cdb92d3b1c6103f420fa3352e` |
| `ggml-small.bin` | `e428ac3ab827de7b1a37328101eaf1ea` |
| `ggml-base-q5_1.bin` | `746f0d70736b2fd77102228cedd6edde` |

## Piper (TTS, резерв)

| Что | Значение |
|---|---|
| Пакет | piper **1.2.0** (`/opt/piper/piper`) |
| Голос | `/opt/piper-voices/ru_RU-irina-medium.onnx` — md5 `21fbe77fdc68bdc35d7adb6bf4f52199` |
| Мета голоса | `ru_RU-irina-medium.onnx.json` — md5 `e239bb7f22d5de4a44ec6b1cb6c06bb5` |

## Parakeet (STT, активный)

| Что | Значение |
|---|---|
| Модель | `nemo-parakeet-tdt-0.6b-v3`, ONNX `istupakov/parakeet-tdt-0.6b-v3-onnx` |
| Обёртка | `/usr/local/bin/parakeet-cli` (bash; интерфейс whisper-cli: `-of`, `-f`) |
| venv | `/opt/parakeet` (Python 3.14.4) |

Пины venv (`/opt/parakeet/bin/pip freeze`, ключевые):

```
onnx-asr==0.12.0
onnxruntime==1.29.0
huggingface_hub==1.29.0
hf-xet==1.6.0
numpy==2.5.2
protobuf==7.36.1
flatbuffers==25.12.19
```

Полный freeze: `anyio==4.14.2, certifi==2026.7.22, click==8.5.0, filelock==3.32.5, fsspec==2026.7.0,
h11==0.16.0, httpcore==1.0.9, httpx==0.28.1, idna==3.19, packaging==26.3, PyYAML==6.0.3,
tqdm==4.70.0, typing_extensions==4.16.0` (плюс перечисленные выше).

## Связи

Ребро графа объявлено в [`../../docs/Восстановление-и-развёртывание.md`](../../docs/Восстановление-и-развёртывание.md)
(генератор графа сканирует только `docs/**`).

Связи[ai-stack-versions]: implements=OPF-4