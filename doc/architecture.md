# Архитектура HostsKeeper v1

## Обзор

```text
┌─────────────────────────────────────────────────────────────┐
│                     HostsKeeper (Windows)                      │
│  ┌─────────┐  ┌──────────────┐  ┌─────────────────────────┐ │
│  │   UI    │──│  App Core    │──│ Encrypted Vault (file)  │ │
│  │ PySide6 │  │  (Python)    │  │ Host/Address/Cred/Script│ │
│  └─────────┘  └──────┬───────┘  └─────────────────────────┘ │
│                      │                                       │
│         ┌────────────┼────────────────┐                      │
│         ▼            ▼                ▼                      │
│  ┌────────────┐ ┌─────────┐   ┌──────────────┐             │
│  │ Session    │ │ Launchers│   │ MCP Server   │             │
│  │ Manager    │ │ PuTTY    │   │ stdio + HTTP │             │
│  │ (SSH/PTY)  │ │ WinSCP   │   │ (LAN bind)   │             │
│  └─────┬──────┘ └─────────┘   └───────┬──────┘             │
└────────┼────────────────────────────────┼───────────────────┘
         │ SSH                            │ key|token / stdio
         ▼                                ▼
   [целевые хосты]                 [Cursor / удалённый ИИ]
   (без доп. ПО)
```

## Принципы

1. **Секреты не покидают сейф** — MCP не отдаёт address/credential/ключи.
2. **Человек открывает сессию** — ИИ только attach к уже живой вкладке.
3. **Один интерактивный PTY на вкладку** — человек и ИИ видят одно содержимое.
   Целевой контракт `scripts_run` использует отдельный SSH `exec`-канал поверх
   transport этой вкладки; он не разделяет shell-контекст PTY и не предоставляет
   общий инструмент удалённого выполнения команд.
4. **Явная выдача доступа** — MCP ON на вкладке + LAN app key (или legacy per-tab token).
5. **Единый remote-first MCP** — localhost и LAN отличаются только адресом.

## Компоненты

### UI

- **Стек:** PySide6 (desktop), пакет `hostskeeper.desktop`. См. [pyside6-migration.md](pyside6-migration.md).
- Стиль: **connection manager** (дерево + тулбар + вкладки) — см. [ui-guidelines.md](ui-guidelines.md).
- Композиция: левое дерево (Hosts/Scripts), тулбар команд, центр с вкладками сессий (alias), status bar.
- Экраны: unlock vault, properties сущностей, терминал во вкладке, MCP URL, Approve checkbox.
- Терминал внутри вкладки: минимальный (текст, ввод, базовая прокрутка); chrome вкладки — в стиле admin workspace.

### App Core (Python)

- Разблокировка/блокировка vault, CRUD сущностей (`hostskeeper.runtime.AppState`).
- Оркестрация открытия сессий и launchers.
- Политики MCP (token, Approve standing permission).
- HTTP MCP (LAN) — фоновый uvicorn; отдельный канал для Cursor.

### Vault

- Один зашифрованный файл (или каталог) на диске.
- Ключ из пароля пользователя при старте (KDF + AEAD; конкретная схема — на этапе реализации).
- В памяти — расшифрованная модель только пока приложение разблокировано.

### Session Manager

- Встроенный SSH-клиент → PTY/channel на вкладку.
- Отдельный `exec`-channel для сохранённых скриптов разрешён только поверх уже
  аутентифицированного transport открытой человеком вкладки; UI может запустить
  сохранённый скрипт во встроенной tab-сессии, MCP — только в MCP-enabled
  сессии с Approve. Новый SSH transport и произвольная команда от модели не
  допускаются.
- Executor/lifecycle использует отдельный channel без PTY, EOF подаётся сразу;
  shell body и ввод не попадают в интерактивный PTY. Сохранённые скрипты,
  запущенные через MCP или явным действием из UI, зеркалируют рамку запуска,
  фактические stdout/stderr и конечный статус в общий session output buffer;
  инициатор отмечается в рамке. UI и MCP `session_read` используют этот же
  буфер. MCP `scripts_run` возвращает только принятие; раздельные ограниченные
  stdout/stderr и состояние доступны через `scripts_run_status` /
  `scripts_run_wait`. Отображение в ленте не означает, что shell body выполнялся
  в PTY, и не фильтрует результат по совпадению со скриптом. MCP lifecycle
  tools не управляют UI-origin запусками; их события и вывод доступны модели
  только как transcript через общий session buffer.
- Безопасная отмена удалённого процесса не гарантируется: закрытие канала при
  cancel, отзыве Approve/MCP или потере сессии даёт `unknown`/`session_lost`,
  не `cancelled`. Целевой shell/OS задаётся SSH-сервером; интерактивные и
  фоновые скрипты не являются поддерживаемым надёжным сценарием.
- Буфер вывода для UI и для MCP (`read` / `subscribe`).
- Состояния: `connecting` | `live` | `disconnected` | `closed`.
- Reconnect по тем же Address+Credential **внутри сейфа** (секреты не уходят в MCP); token MCP сохраняется.

### Launchers

- PuTTY: запуск внешнего процесса с параметрами сессии (без MCP).
- WinSCP: аналогично для SFTP/SCP (без MCP).

### MCP Server

| Канал | Bind / запуск | Auth | Видимость |
|-------|---------------|------|-----------|
| HTTP gateway | LAN (и localhost) | стабильный app key (`?key=` / заголовок) | все mcp-enabled вкладки + MCP-enabled скрипты в доступном host scope |
| HTTP legacy | LAN (и localhost) | per-tab token в URL | одна вкладка + MCP-enabled скрипты в доступном host scope |
| stdio | процесс MCP | доверенный локальный | все MCP-вкладки + MCP-enabled скрипты в доступном host scope |

Ограничение legacy: **1 клиент на tab-token**. Gateway: выбор вкладки через `alias` / `session_attach`.

Подробный контракт tools: [mcp-api.md](mcp-api.md).

## Потоки

### Открытие вкладки и выдача ИИ

```text
Человек: Host → Address + Credential → «Открыть во вкладке»
       → alias (или автопредложение)
       → MCP ON → session_list / session_attach (Cursor mcp.json с app key)
ИИ:     HTTP connect (app key) → session_list → session_attach(alias)
       → subscribe / read / write / scripts_*
```

### Запись с Approve

```text
ИИ: session_write / scripts_run
Core: если Approve выкл → сразу approve_required (чтение терминала разрешено)
      если Approve вкл  → байты в PTY без модалки
```

### Обрыв SSH

```text
PTY/SSH down → status=disconnected
MCP button остаётся, token жив
Tools → ошибка disconnected
Человек: Reconnect в UI → status=live, тот же token
```

## Границы доверия

| Зона | Доверие |
|------|---------|
| Процесс HostsKeeper + расшифрованный vault в RAM | Полное |
| stdio MCP на той же машине | Высокое (как локальный агент) |
| HTTP MCP в LAN | App key (gateway) или legacy tab token |
| Целевой хост | Обычный SSH; ПО сейфа туда не ставится |
| Чат Cursor | Alias; mcp.json держит стабильный app key |

App key в mcp.json — осознанный риск LAN v1; вкладки всё равно требуют MCP ON.

## Расширяемость (после v1)

- Backup/export vault
- Jump/ProxyJump, 2FA-хуки
- Импорт SSH config / Termius
- Более богатый терминал
- Общий произвольный non-interactive exec с сейфа (узкий `exec`-канал только
  для `scripts_run` не разрешает такой функциональности)
- Несколько клиентов / роли
