# Контракт MCP API (v1)

## Подключение

### HTTP (LAN) — рекомендуемый режим: app key

- Сервер слушает на LAN (host/port приложения).
- Клиент подключается со **стабильным app key** приложения (не per-tab).
- Key: `~/.hostskeeper/mcp.key`, env `HOSTSKEEPER_MCP_KEY`, или `--mcp-key`.
- URL для Cursor (один раз в mcp.json; toolbar **Copy MCP config**):

```text
http://<safe-host>:<port>/mcp?key=<app-key>
```

Также: заголовок `X-HostsKeeper-Key` или `Authorization: Bearer <app-key>`.

- Область: все вкладки с `mcp_enabled=true` + все скрипты (как stdio).
- Выбор вкладки: `session_list` → `session_attach(alias=…)` или `alias`/`session_id` в каждом tool.
- Человек по-прежнему обязан включить **MCP** на нужных вкладках.

Пример Cursor `mcp.json`:

```json
{
  "mcpServers": {
    "hostskeeper": {
      "url": "http://127.0.0.1:8765/mcp?key=<app-key>"
    }
  }
}
```

### HTTP — legacy: per-tab token

```text
http://<safe-host>:<port>/mcp?token=<tab-token>
```

- Привязка к одной сессии; **1 клиент на token** → иначе `client_busy`.
- Область: эта сессия + все скрипты.

### stdio

- Локальный процесс без token/key.
- Видит все сессии с `mcp_enabled=true` и все скрипты.
- Идентификация сессии — `alias` / `session_id` / `session_attach`.

## Общие соглашения

- Секреты и сетевые параметры хостов **не** возвращаются ни в одном tool.
- Approve (чекбокс на вкладке): **выкл по умолчанию** — MCP только читает терминал; `session_write` / `scripts_run` сразу → `approve_required`. **вкл** — write/run без модалки и без таймаута.
- При `status=disconnected` операции ввода/чтения потока завершаются ошибкой `disconnected` (кроме информационных, где status явно отдаётся).

## Tools

### session_info

Описание сессии для диалога с человеком.

**HTTP legacy token:** сессия из token (аргументы не обязательны).  
**HTTP gateway / stdio:** `session_id` или `alias`, либо ранее `session_attach`.

Вход:

```json
{ "session_id": "uuid?", "alias": "string?" }
```

Выход:

```json
{
  "session_id": "uuid",
  "alias": "string",
  "status": "live|disconnected|connecting",
  "approve_enabled": false,
  "alt_screen": false,
  "screen_tail": "plain text of visible PTY screen (no CSI)",
  "host_id": "uuid",
  "host_profile_present": false,
  "host_profile_chars": 0,
  "host_profile_hint": "…"
}
```

`screen_tail` / `alt_screen` публикует UI-вкладка (pyte). Пока вкладка не открыта в desktop UI — пустая строка / `false`.  
`alt_screen=true` — TUI на alternate screen (htop/vim/…); после выхода экран primary восстанавливается.

После `session_attach` / `session_info`: сначала `host_profile_get`. Если Notes пустые или скудные — предложить пользователю заполнить; по согласию собрать факты через PTY (нужен Approve) и сохранить `host_profile_set`.

### host_profile_get / host_profile_set

Свободный текст Host Notes (вкладка Edit Host → **Notes**). Без адресов/учёток/секретов.  
Доступ только к хостам, для которых есть открытая MCP-вкладка. Approve не требуется.

Вход get: `{ "session_id"?, "alias"?, "host_id"? }` (иначе — сессия из attach/token).  
Вход set: то же + `{ "profile": "string" }`.

### session_list

Список сессий в scope клиента (gateway/stdio — все mcp-enabled; legacy HTTP — одна).

Выход:

```json
{
  "sessions": [
    { "session_id": "uuid", "alias": "string", "status": "live|disconnected|connecting" }
  ]
}
```

### session_attach

Закрепить default-сессию для gateway/stdio (по `alias`, `session_id` или legacy `tab_token`).

```json
{ "alias": "lab-red-1", "session_id": "uuid?", "tab_token": "string?" }
```

Выход: `{ "ok": true, "alias": "…", "session_id": "…", "pinned": true }`.

### session_read

Новые строки с внутреннего курсора клиента (или с указанного `cursor`).

Вход:

```json
{
  "session_id": "uuid?",
  "alias": "string?",
  "cursor": "string?",
  "max_bytes": 65536
}
```

Выход:

```json
{
  "alias": "string",
  "status": "live|disconnected|connecting",
  "cursor": "string",
  "data": "string",
  "truncated": false
}
```

### session_subscribe

В v1 реализовано как **long-poll tool** (не отдельный SSE subscription bus): ждёт новые данные или смену статуса до `timeout_sec` (default 30).

Вход: идентификация сессии + опционально `cursor` + `timeout_sec`.

Ответ:

```json
{ "type": "output", "alias": "string", "cursor": "string", "data": "string" }
{ "type": "status", "alias": "string", "status": "disconnected|live|closed" }
```

### Реализация

- Пакет: `hostskeeper.mcp` (`McpToolService`, `build_mcp_server`, `create_http_app`, `app_key`).
- HTTP: `?key=` (gateway) или `?token=` (legacy); bind default `0.0.0.0:8765`.
- Middleware: без key/token → 401; legacy второй клиент на token → 409 `client_busy`.
- Streamable HTTP создаётся с `host=` = bind-адрес (`0.0.0.0` для LAN). Иначе SDK
  включает DNS-rebinding allowlist только для localhost и отвергает
  `Host: <lan-ip>:8765` (Cursor зависает в Connecting).

### session_write

Отправка текста в PTY (как ввод пользователя).

Вход:

```json
{
  "session_id": "uuid?",
  "alias": "string?",
  "text": "string",
  "submit": true
}
```

`submit=true` — добавить перевод строки в конце (удобно для команд), если ещё нет.

Выход:

```json
{ "ok": true, "alias": "string" }
```

Ошибки: `disconnected`, `approve_required`, `client_scope`.

### scripts_list

Шаблоны (`host_id=null`) — всегда. Скрипты хоста — только если у клиента есть открытая MCP-вкладка этого хоста.

Выход: `id`, `name`, `description`, `tags`, `parameters` (без `user_value`), `host_id`, `group_id`.

### scripts_get

Вход: `{ "id"?, "name"?, "host_id"? }` — `host_id` для однозначности имени host-скрипта.

Выход: полная карточка включая `body`; в `parameters` нет `user_value`.

### scripts_create / scripts_update

Вход: поля Script + опционально `host_id`, `group_id`.  
`host_id` при create — только при открытой MCP-вкладке этого хоста.  
Update — по `id` или `name` (+ `host_id` при неоднозначности).  
Входящий `user_value` в parameters **игнорируется**; при update существующие `user_value` по совпавшему `name` сохраняются.

Без approve.

### scripts_delete

Вход: `{ "id"?, "name"?, "host_id"? }`

Без approve.

### scripts_run

Подстановка параметров (`params` / `default`) → вставка в PTY. Поле `user_value` **не используется** (только UI Run с «Use user values» → PuTTY).  
Шаблон — в любую доступную сессию. Host-скрипт — **только** в сессию того же хоста.

Вход:

```json
{
  "session_id": "uuid?",
  "alias": "string?",
  "script_id": "uuid?",
  "name": "string?",
  "host_id": "uuid?",
  "params": { "iface": "eth0" },
  "submit": true
}
```

Ошибки: `missing_param`, `unknown_placeholder`, `disconnected`, `approve_required`, `client_scope`.

### groups_list / groups_create / groups_update / groups_delete

Дерево групп (`kind=scripts|hosts`). Шаблонные scripts-группы всегда; host-группы — при открытой вкладке хоста.  
Create: `name`, `kind?`, `parent_id?`, `host_id?`. Update/delete по `id`. Без approve.

## Ошибки (логический код)

| code | Когда |
|------|--------|
| `unauthorized` | Нет/неверный app key или tab token (HTTP) |
| `client_busy` | Слот клиента на legacy token занят |
| `not_found` | Нет сессии/скрипта в scope |
| `disconnected` | SSH/PTY не live |
| `approve_required` | Approve выкл — write/run запрещены |
| `invalid_args` | Валидация входа |
| `missing_param` | Нет обязательного параметра скрипта |
| `unknown_placeholder` | В body остался незакрытый/неизвестный `{{...}}` |

## Чего нет в v1

- Tools для списка хостов/адресов/учёток (кроме Notes текущего MCP-хоста: `host_profile_*`)
- Открытие новой SSH-сессии силами ИИ
- Доступ к PuTTY/WinSCP окнам
- Выдача секретов «для отладки»
