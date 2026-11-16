# Контракт MCP API (v1)

## Подключение

### HTTP (LAN) — рекомендуемый режим: app key

- Сервер слушает на LAN (host/port приложения).
- Клиент подключается со **стабильным app key** приложения (не per-tab).
- Key: `~/.hostskeeper/mcp.key`, env `HOSTSKEEPER_MCP_KEY`, или `--mcp-key`.
- Смена ключа: Options → **Change MCP Key** (перезаписывает файл; старый ключ сразу 401). Затем снова **Copy MCP config**.
- Options → **Copy MCP config** копирует готовую запись для VS Code (`mcp.json`); ключ передаётся заголовком `X-HostsKeeper-Key`, не в URL.
- Сервер также принимает `?key=<app-key>` и `Authorization: Bearer <app-key>` для совместимости.

- Область: все вкладки с `mcp_enabled=true` + все скрипты (как stdio).
- Выбор вкладки: `session_list` → `session_attach(alias=…)` или `alias`/`session_id` в каждом tool.
- Человек по-прежнему обязан включить **MCP** на нужных вкладках.

Пример VS Code `mcp.json`:

```json
{
  "servers": {
    "hostskeeper": {
      "type": "http",
      "url": "http://127.0.0.1:8765/mcp",
      "headers": {
        "X-HostsKeeper-Key": "<app-key>"
      }
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
- В `initialize.result` сервер передаёт workflow в `instructions`; `serverInfo.version` соответствует версии пакета.
- Успешный `tools/call` возвращает объект в `structuredContent` и его JSON-представление в `content`. Ошибки инструментов имеют `isError=true` и содержат прикладной код/сообщение; ошибки JSON-RPC протокола остаются отдельными.
- `notifications/initialized` не возвращает JSON-RPC body (Streamable HTTP отвечает `202 Accepted` с пустым телом). Для POST MCP-клиент должен объявить поддержку `application/json` и `text/event-stream`; GET используется для SSE-потока.

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

Текст из буфера вывода, начиная с `cursor`.

Вход:

```json
{
  "session_id": "uuid?",
  "alias": "string?",
  "cursor": "string?",
  "max_bytes": 65536
}
```

Несмотря на историческое имя, `max_bytes` ограничивает число символов, а не UTF-8 байтов; допустимо `1..1048576`. Без cursor чтение начинается с начала сохранённого буфера. Используйте возвращённый `cursor` для следующей порции. `truncated=true` означает, что в буфере остались данные. Cursor — строковое представление смещения в символах, а не непрозрачный токен. Это bounded-чтение по cursor, не режим «последние N строк»; уменьшайте `max_bytes`, если клиенту нужен небольшой ответ.

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

При таймауте возвращается `type=output` с пустым `data` и актуальным cursor.

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
`ok=true` подтверждает, что текст отправлен в SSH-канал интерактивного PTY, но
не означает, что команда завершилась или выполнилась успешно. Echo и результат
видны в общем буфере терминала; используйте `session_read` или
`session_subscribe`, чтобы читать их отдельно.

Выход:

```json
{ "ok": true, "alias": "string" }
```

Ошибки: `disconnected`, `approve_required`, `client_scope`.

### scripts_list

Шаблоны (`host_id=null`) — всегда. Скрипты хоста — только если у клиента есть открытая MCP-вкладка этого хоста.

Выход: `id`, `name`, `scope` (`template` или `host`), `host_alias` (alias доступной вкладки хоста или `null`), `description`, `tags`, `parameters` (без `user_value`), `host_id`, `group_id`.

Если имя совпадает у нескольких видимых скриптов, используйте `id` из списка или явно укажите `host_id`; выбор по неоднозначному имени завершается `invalid_args`.

### scripts_get

Вход: `{ "id"?, "name"?, "host_id"? }` — `host_id` для однозначности имени host-скрипта.

Выход: полная карточка включая `body`; в `parameters` нет `user_value`.
При `not_found` обновите `scripts_list`: host-скрипт виден только при открытой
MCP-вкладке этого хоста. Отсутствующий и недоступный по scope скрипты намеренно
неразличимы.

### scripts_validate

Read-only preflight для draft скрипта. Ничего не сохраняет, не рендерит shell
текст и не пишет в PTY.

Вход:

```json
{
  "body": "echo {{iface}}",
  "parameters": [
    { "name": "iface", "required": true }
  ],
  "params": { "iface": "eth0" }
}
```

`parameters` и `params` необязательны. Значения из `params` используются только
для определения готовности к рендерингу и никогда не возвращаются.

Выход:

```json
{
  "valid": true,
  "ready_to_run": true,
  "placeholders": [{ "name": "iface", "position": 5 }],
  "errors": [],
  "warnings": [],
  "missing_parameters": []
}
```

`position` — нулевое смещение в символах. `valid` означает, что синтаксис
placeholders и их объявления согласованы; `ready_to_run` также учитывает
отсутствующие значения. `missing_parameters` содержит используемые в body
placeholders, для которых не передано значение и не задан default; `warnings`
включает объявленные, но неиспользуемые параметры. Ответ не содержит body,
defaults или переданных значений.

### scripts_create / scripts_update

Вход: поля Script + опционально `host_id`, `group_id`.  
`host_id` при create — только при открытой MCP-вкладке этого хоста.  
Update — по `id` или `name` (+ `host_id` при неоднозначности).  
Входящий `user_value` в parameters **игнорируется**; при update существующие `user_value` по совпавшему `name` сохраняются.

Перед записью проверяются placeholder-синтаксис, имена параметров и наличие
объявления для каждого placeholder; несовместимое обновление не меняет
сохранённый скрипт. Неиспользуемые объявления допустимы и возвращаются в
`scripts_validate` как предупреждения. Без Approve.

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

Ответ `scripts_run`:

```json
{ "ok": true, "alias": "…" }
```

`ok=true` означает только отправку отрендеренного текста в PTY. Инструмент не ждёт
завершения команды и не возвращает exit status. Читайте общий вывод через
`session_read` или `session_subscribe`; echo отправленного скрипта может быть
частью этого вывода.

### groups_list / groups_create / groups_update / groups_delete

Дерево групп (`kind=scripts|hosts`). Шаблонные scripts-группы всегда; host-группы — при открытой вкладке хоста.  
Поле `expanded` (UI) в ответах **не** отдаётся.  
Create: `name`, `kind?`, `parent_id?`, `host_id?`. Update/delete по `id`. Без approve.  
`groups_delete` — **рекурсивно** удаляет подгруппы и всё содержимое (hosts/scripts/notes).

### notes_list / notes_get / notes_create / notes_update / notes_delete

Только заметки с `mcp_enabled=true`. Видимость host-local — как у scripts (нужна MCP-вкладка хоста).  
Create всегда ставит `mcp_enabled=true` (параметра нет). Update **не** меняет `mcp_enabled`. Без Approve.  
Поля: `name`, `body` (Markdown), `group_id?`, `host_id?`.

## Ошибки (логический код)

| code | Когда |
|------|--------|
| `unauthorized` | Нет/неверный app key или tab token (HTTP) |
| `client_busy` | Слот клиента на legacy token занят |
| `not_found` | Нет сессии/скрипта в scope. Для скрипта обновите `scripts_list`; host-скрипты требуют открытой MCP-вкладки своего хоста |
| `disconnected` | SSH/PTY не live |
| `approve_required` | Approve выкл — write/run запрещены |
| `invalid_args` | Валидация входа; при сохранении скрипта — некорректный placeholder или объявления параметров |
| `missing_param` | Нет значения для используемого placeholder |
| `unknown_placeholder` | В body остался незакрытый/неизвестный `{{...}}` |

## Чего нет в v1

- Tools для списка хостов/адресов/учёток (кроме Notes текущего MCP-хоста: `host_profile_*`)
- Открытие новой SSH-сессии силами ИИ
- Доступ к PuTTY/WinSCP окнам
- Выдача секретов «для отладки»
