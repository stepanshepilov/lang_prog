# Лабораторная 1 — AI-чат с MCP

Требуется Python 3.15.x и Poetry. Все команды запускаются из корня проекта.

## Подготовка

```sh
poetry env use python3.15
poetry install
```

Если `.env` ещё не создан, скопируйте шаблон командой `cp .env.example .env`. Укажите `LLM_API_KEY`; при необходимости измените `LLM_API_URL` и `LLM_MODEL`. MCP отдельного токена не требует.

## Запуск

Сначала запустите MCP-сервер в первом терминале:

```sh
poetry run python -m uvicorn task_1.mcp_md_server:app --host 0.0.0.0 --port 8001
```

Затем во втором терминале загрузите настройки LLM и запустите чат (команды для macOS/Linux):

```sh
set -a
. ./.env
set +a
poetry run python -m uvicorn task_1.chat_server:app --host 0.0.0.0 --port 8000
```

Откройте <http://localhost:8000>. MCP endpoint доступен по адресу <http://localhost:8001/mcp>. Сервер работает с `.md`-файлами в `task_1/documents/`.
