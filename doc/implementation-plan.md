# План реализации HostsKeeper v1

Документ опирается на [requirements.md](requirements.md), [architecture.md](architecture.md), [data-model.md](data-model.md), [mcp-api.md](mcp-api.md), [ui-guidelines.md](ui-guidelines.md).

## Цель v1

Рабочее Windows-приложение: зашифрованный vault, ручные SSH-вкладки с общим PTY, launchers PuTTY/WinSCP, MCP (stdio + HTTP LAN) для read/subscribe/write и CRUD/run скриптов.

Готовые «боевые» скрипты под инфраструктуру пользователя **не** входят в разработку — нужна только подсистема скриптов.

## Принципы ведения работ

1. Сначала ядро без полировки UI.
2. Секреты и MCP-границы закладывать сразу, не «потом ужесточим».
3. Каждый этап заканчивается проверяемым инкрементом.
4. PuTTY/WinSCP не блокируют путь к MCP (MCP только от вкладок).

---

## Этап 0 — Каркас репозитория

**Результат:** структура проекта, окружение Python, точка входа, README корня, этот `doc/`.

- [x] Git init, `.gitignore`
- [x] Документация в `doc/`
- [x] `AGENTS.md`, `.cursor/rules/`, `doc/agent-prompts/` (подготовка оркестрации)
- [x] Каркас Python-пакета (`pyproject.toml` / requirements)
- [x] Пакеты: `hostskeeper.vault`, `hostskeeper.session`, `hostskeeper.mcp`, `hostskeeper.api` (имена уточняемы)
- [x] Команда запуска dev (пока CLI/заглушка)

**Критерий:** `python -m hostskeeper` (или аналог) стартует и печатает версию. ✅

---

## Этап 1 — Vault

**Результат:** создание/открытие vault по паролю, CRUD Host/Address/Credential/Script в памяти + persist.

Задачи:

- [x] Выбор формата контейнера: JSON внутри Scrypt + AES-256-GCM (`HSVAULT1`)
- [x] Unlock / lock (смена пароля — позже)
- [x] CRUD сущностей по [data-model.md](data-model.md)
- [x] Defaults у Host
- [x] Юнит-тесты: round-trip encrypt, отказ при неверном пароле, secret-поля не светятся в `repr`

**Критерий:** CLI или временный API создаёт host+address+credential+script и переживает рестарт процесса. ✅ (`Vault` API + `pytest`)

**Не входит:** UI просмотра секретов (можно CLI-флаг), backup.

---

## Этап 2 — Session Manager + SSH-вкладка (headless)

**Результат:** программное открытие SSH-сессии, буфер вывода, write, disconnect/reconnect, alias.

Задачи:

- [x] SSH-клиент на Python (**Paramiko**) → интерактивный shell channel
- [x] Модель Session runtime
- [x] Последовательный буфер + cursor для `read`
- [x] Генерация alias `host-user-N` + ручное задание
- [x] Статусы `live` / `disconnected` / `closed`
- [x] Reconnect теми же id сущностей vault (секреты только внутри core)

**Критерий:** интеграционный тест/скрипт: логин на тестовый хост (или sshd в Docker/WSL), echo виден в буфере, write доставляет команду. ✅ (`tests/test_session_ssh_integration.py`)

**Не входит:** красивый xterm; пока достаточно захвата байтов/текста.

---

## Этап 3 — MCP: сессии

**Результат:** MCP stdio + HTTP LAN с token, tools сессии.

Задачи:

- [x] SDK: `mcp` 2.x (`MCPServer`) + Streamable HTTP (Starlette/uvicorn)
- [x] Выдача/отзыв per-tab token; URL для копирования (`SessionManager.mcp_url`)
- [x] 1 клиент на token (`client_busy`)
- [x] Tools: `session_info`, `session_list`, `session_read`, `session_subscribe` (long-poll), `session_write`
- [x] stdio: все mcp-enabled сессии; HTTP: одна сессия token
- [x] Ошибки `disconnected`, `client_busy`, `unauthorized`
- [x] Проверка: из MCP **не** утекают host/password/key (тесты на ответы)

**Критерий:** Cursor (или MCP Inspector) по URL читает вывод и пишет в живую сессию. ✅ (сервисный слой + HTTP middleware; полный Cursor UI — этап 6)

---

## Этап 4 — Approve

**Результат:** per-session checkbox (standing permission: off=read-only MCP, on=write/run).

Задачи:

- [x] Per-session `approve_enabled` (default false)
- [x] `session_write` / `scripts_run` требуют Approve; иначе `approve_required`
- [x] Checkbox на chrome вкладки (без модалки/таймаута)

**Критерий:** Approve off → write сразу отклонён, PTY чист; Approve on → write в PTY. ✅

---

## Этап 5 — Скрипты в MCP

**Результат:** CRUD + run с `{{params}}` в PTY.

Задачи:

- [x] Парсинг плейсхолдеров, валидация required/default
- [x] Tools `scripts_*` по [mcp-api.md](mcp-api.md)
- [x] `scripts_run` → тот же путь approve, что `session_write`
- [x] HTTP: run только в token-сессию

**Критерий:** создать скрипт через MCP, запустить с params, в терминале виден подставленный текст. ✅

---

## Этап 6 — UI (connection-manager workspace)

**Результат:** usable desktop/web UI поверх core в стиле [ui-guidelines.md](ui-guidelines.md).

Задачи:

- [x] Выбор: **FastAPI + static UI в браузере** (без Tauri в v1); позже заменён PySide6 (этапы 9–14)
- [x] Каркас layout: дерево слева + тулбар + вкладки + status bar
- [x] Unlock vault
- [x] CRUD Host / Address / Credential / Script (модальные property-формы)
- [x] Кнопка «показать секрет» (локально)
- [x] Open Tab из дерева/ленты; PuTTY/WinSCP — заглушки этапа 7
- [x] Вкладка терминала (poll) + chrome с alias / MCP / approve
- [x] MCP ON/OFF, copy URL, connect/disconnect all
- [x] Approve dialog + countdown
- [x] Reconnect / Disconnect / Close
- [x] Статусы цветом в дереве/вкладках

**Критерий:** полный сценарий «человек + Cursor» без CLI; layout узнаваемо близок к connection manager (дерево + тулбар + вкладки), не к чат-приложению. ✅ (ручной прогон в браузере; API smoke в pytest)

---

## Этап 7 — Launchers PuTTY / WinSCP

**Результат:** внешний запуск без MCP.

Задачи:

- [x] Обнаружение путей / env `HOSTSKEEPER_PUTTY` / `HOSTSKEEPER_WINSCP`
- [x] OpenSSH PEM → `.ppk` (WinSCP.com `/keygen` или puttygen); пароль не в cmdline
- [x] WinSCP: `/privatekey=` + `/hostkey=acceptnew`
- [x] Launchers не создают MCP-сессии; кнопки в тулбаре UI

**Критерий:** из UI открывается PuTTY и WinSCP к выбранной комбинации. ✅

---

## Этап 8 — Стабилизация v1

**Результат:** упаковка, жёсткость границ, документация пользователя.

Задачи:

- [x] Обрывы: status `disconnected` + Reconnect; буфер с лимитом
- [x] MCP host/port через CLI (`--mcp-host` / `--mcp-port`); предупреждение в user-guide
- [x] Без отдельного логгера секретов (не логируем credential fields)
- [x] `doc/user-guide.md`
- [x] `doc/regression-checklist.md`

**Критерий:** чеклист пройден на машине разработчика с реальным Cursor по LAN/localhost. ⏳ (автотесты + UI API; финальный Cursor LAN — с человеком)

---

## Порядок зависимостей

```text
0 Каркас
 └─ 1 Vault
      └─ 2 Session/SSH
           ├─ 3 MCP sessions ─┬─ 4 Approve ─┬─ 5 Scripts MCP
           │                  │             │
           └──────────────────┴─────────────┴─ 6 UI ─ 7 Launchers ─ 8 Stabilize
```

Этапы 4 и 5 можно частично параллелить после 3. Launchers (7) можно начать сразу после 1+черновика UI, не блокируя MCP.

---

## Риски и смягчение

| Риск | Смягчение |
|------|-----------|
| Сложность MCP HTTP в экосистеме Cursor | Сначала stdio end-to-end, затем HTTP; проверить актуальную схему Cursor |
| Paramiko/PTY vs «как в PuTTY» | Явно минимализм; не гнаться за полным VT100 в v1 |
| Token в чате | Короткий срок жизни = пока MCP ON; только LAN; 1 клиент |
| Утечка секретов в логи/MCP | Тесты на красные поля; централизованный serializer |
| UI раздувается | Сначала thin UI на API core |

---

## Definition of Done (v1)

- Vault с паролем; Host/Address/Credential/Script.
- Вкладка SSH: человек и ИИ на одном PTY.
- MCP stdio + HTTP LAN; copy URL; alias через `session_info`.
- Approve per-session с timeout.
- Скрипты CRUD/run с `{{params}}`.
- PuTTY и WinSCP из UI без MCP.
- Секреты и адреса недоступны через MCP (покрыто тестами).
- Документация в `doc/` соответствует факту реализации (обновить по итогам).

---

## После v1 — UI на PySide6 (этапы 9–14)

Web UI этапа 6 — временный инкремент. Переход на native desktop: **[pyside6-migration.md](pyside6-migration.md)**.

| Этап | Кратко |
|------|--------|
| 9 | Каркас PySide6 + unlock |
| 10 | Дерево + CRUD properties |
| 11 | SSH-вкладки + терминал |
| 12 | MCP chrome + Approve |
| 13 | Launchers в Qt |
| 14 | Вывод web UI + обновление docs |

Старт только по команде человека/оркестратора. Ядро vault/session/mcp/launchers не переписывать.
