# Контракт MCP API (v1)

## Подключение

### HTTP (LAN) — рекомендуемый режим: app key

- Сервер слушает на LAN (host/port приложения).
- Клиент подключается со **стабильным app key** приложения (не per-tab).
- Key: `~/.hostskeeper/mcp.key`, env `HOSTSKEEPER_MCP_KEY`, или `--mcp-key`.
- Смена ключа: Options → **Change MCP Key** (перезаписывает файл; старый ключ сразу 401). Затем снова **Copy MCP config**.
- Options → **Copy MCP config** копирует готовую запись для VS Code (`mcp.json`); ключ передаётся заголовком `X-HostsKeeper-Key`, не в URL.
- Сервер также принимает `?key=<app-key>` и `Authorization: Bearer <app-key>` для совместимости.

- Область: все вкладки с `mcp_enabled=true` + скрипты с включённым MCP в доступном host scope.
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
- Область: эта сессия + скрипты с включённым MCP в доступном host scope.

### stdio

- Локальный процесс без token/key.
- Видит все сессии с `mcp_enabled=true` и скрипты с включённым MCP в доступном host scope.
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
Общий session buffer удерживает до 1000000 символов и при переполнении удаляет
старые порции. Если cursor указывает на уже вытесненные данные, чтение начинает
с самой старой сохранённой позиции; `truncated` означает только наличие
следующих сохранённых данных, а не потерю истории.
Буфер содержит вывод интерактивного PTY и размеченный transcript запусков
сохранённых скриптов из UI и MCP: рамку запуска, фактические stdout/stderr и
конечный статус. Эти скрипты исполняются на отдельном SSH exec-channel;
отображение в общей ленте не передаёт их body в PTY. MCP `scripts_run_wait`
дополнительно возвращает stdout и stderr отдельно.

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

Только скрипты с `mcp_enabled=true`. Шаблоны (`host_id=null`) доступны всегда; скрипты хоста — только если у клиента есть открытая MCP-вкладка этого хоста.

Выход: `id`, `name`, `scope` (`template` или `host`), `host_alias` (alias доступной вкладки хоста или `null`), `description`, `tags`, `parameters` (без `user_value`), `host_id`, `group_id`, `mcp_enabled` (`true`).

Если имя совпадает у нескольких видимых скриптов, используйте `id` из списка или явно укажите `host_id`; выбор по неоднозначному имени завершается `invalid_args`.

### scripts_get

Вход: `{ "id"?, "name"?, "host_id"? }` — `host_id` для однозначности имени host-скрипта.

Выход: полная карточка включая `body`; в `parameters` нет `user_value`.
При `not_found` обновите `scripts_list`: любой скрипт должен иметь включённый
чекбокс MCP, а host-скрипт — также открытую MCP-вкладку этого хоста.
Отсутствующий и недоступный скрипты намеренно неразличимы.

### scripts_compare

Read-only сравнение двух явно выбранных скриптов. Оба ID должны быть доступны в
scope текущего клиента (у обоих включён MCP; шаблоны доступны всегда;
host-bound скрипты — при открытой MCP-вкладке соответствующего хоста).
Недоступный и отсутствующий ID неразличимы. Никакие данные vault не меняются.

Вход:

```json
{
  "left_script_id": "uuid",
  "right_script_id": "uuid"
}
```

Выход содержит идентификаторы/имена сторон, отличающиеся поля `name`,
`description`, `parameters` с обеими версиями, а также unified diff body.
В параметрах нет `user_value`. Diff ограничен 20 000 символами; если он длиннее,
`body_diff_truncated=true` и в конце diff указывается усечение.

```json
{
  "left": { "id": "uuid", "name": "template" },
  "right": { "id": "uuid", "name": "host-script" },
  "metadata_differences": {
    "description": { "left": null, "right": "Host-specific behavior" },
    "parameters": {
      "left": [],
      "right": [
        {
          "name": "port",
          "description": null,
          "required": true,
          "default": "2222"
        }
      ]
    }
  },
  "body_diff": "--- <left-id>\n+++ <right-id>\n@@ ...",
  "body_diff_truncated": false
}
```

### scripts_validate

Read-only **статическая** проверка draft скрипта перед сохранением или запуском.
Проверяет только синтаксис placeholders, их объявления и готовность значений к
подстановке. Ничего не сохраняет, не рендерит shell-текст и не пишет в PTY.
Она не исполняет и не разбирает shell-команды, не оценивает безопасность команд
и не гарантирует корректность для shell, ОС или конкретного хоста.

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

Рекомендуемый workflow для MCP-клиента: явно попросить вызвать
`scripts_validate` для draft, затем при необходимости сохранить/запустить его.
Сервер рекламирует tool в `tools/list` и в server instructions, но выбор tool
для конкретного запроса выполняет сам клиент/planner; доступность в списке не
гарантирует автоматический вызов. Client-side инструкция может звучать так:
«Для draft скрипта сначала вызови HostsKeeper `scripts_validate`; трактуй
результат только как проверку placeholders, не как проверку безопасности или
успешности исполнения».

### scripts_create / scripts_update

Вход: поля Script + опционально `host_id`, `group_id`.  
`host_id` при create — только при открытой MCP-вкладке этого хоста.  
Скрипты, созданные через MCP, сразу получают `mcp_enabled=true`;
`scripts_update` не меняет этот флаг. Видимостью управляет UI-чекбокс MCP.
Update — по `id` или `name` (+ `host_id` при неоднозначности); доступны только скрипты с включённым MCP в текущем scope.
Входящий `user_value` в parameters **игнорируется**; при update существующие `user_value` по совпавшему `name` сохраняются.

Перед записью проверяются placeholder-синтаксис, имена параметров и наличие
объявления для каждого placeholder; несовместимое обновление не меняет
сохранённый скрипт. Неиспользуемые объявления допустимы и возвращаются в
`scripts_validate` как предупреждения. Без Approve.

### scripts_delete

Вход: `{ "id"?, "name"?, "host_id"? }`

Без approve.

### scripts_run

Запускает сохранённый MCP-visible скрипт через отдельный SSH exec-channel
открытой человеком MCP-вкладки; общий PTY не используется для исполнения.
Рамка запуска, фактический вывод и конечный статус при этом зеркалируются в
общий session output buffer, видимый в терминале и через `session_read`. Поле
`user_value` **не используется** (только UI Run с «Use user values» → PuTTY).
Host-bound скрипт запускается только во вкладке того же хоста. До принятия
запуска сервер повторно проверяет видимость скрипта, scope вкладки, live-состояние
и Approve. Случайный shell body не принимается.

Вход:

```json
{
  "session_id": "uuid?",
  "alias": "string?",
  "script_id": "uuid?",
  "name": "string?",
  "host_id": "uuid?",
  "params": { "iface": "eth0" },
  "request_id": "uuid"
}
```

`request_id` — UUID от клиента для одного намерения запуска. Повтор с тем же
`request_id` в той же сессии возвращает исходный run без повторного запуска;
для нового запуска нужен новый ID. `state="accepted"` подтверждает первоначальное
принятие намерения, а `current_state` сообщает последнее состояние записи на
момент ответа. `replayed=true` означает, что запрос уже принимался ранее.
Ответ:

```json
{
  "run_id": "uuid",
  "state": "accepted",
  "accepted_at": "2026-11-17T10:00:00Z",
  "replayed": false,
  "current_state": "running"
}
```

При повторе ответ сохраняет `state="accepted"` как семантику первоначального
подтверждения, возвращает прежние `run_id` и `accepted_at`, устанавливает
`replayed=true`, а `current_state` показывает существующее состояние, например
`succeeded`. Клиент может вызвать `scripts_run_status` / `scripts_run_wait` для
более свежего снимка. `accepted` подтверждает только принятие запроса
HostsKeeper, а не запуск либо успешное выполнение на target host. Ошибки включают `missing_param`,
`unknown_placeholder`, `disconnected`, `approve_required`, `client_scope`,
`run_capacity` и общий `not_found` для недоступного скрипта.
`run_capacity` сохраняет стабильный код, а сообщение указывает применимый
лимит: один активный/неопределённый run на сессию, восемь на процесс или 100
удерживаемых записей. Запуск не ставится в очередь. Неопределённый run может
резервировать слот сессии до истечения записи; его закрытие или срок retention
не подтверждают остановку удалённого процесса.

### scripts_run_status / scripts_run_wait / scripts_run_cancel

Инструменты принимают `run_id` и проверяют, что исходная сессия всё ещё входит
в MCP scope клиента. Доступны только lifecycle-записи, запущенные через MCP;
`run_id` UI-запуска, видимый в общем transcript, намеренно возвращает общий
`not_found` для status/wait/cancel. Для выбора сессии доступны
`session_id`/`alias`; HTTP legacy token остаётся ограничен своей вкладкой.
Status/wait/cancel не требуют Approve для MCP-origin запусков.
`scripts_run_wait` дополнительно принимает
`timeout_sec` (`30` default, `0..30`), `stdout_cursor?`, `stderr_cursor?` и
`max_chars` (`16384` default, `1..65536` суммарно по двум потокам). Окончание
ожидания возвращается как `wait_timed_out=true`, не меняя state. `status` не
возвращает output; `wait` возвращает новые порции stdout/stderr; `cancel`
запрашивает остановку и не обещает её до подтверждения.
Если подтверждения нет, `cancel` закрывает локальный SSH-канал, а запись
переходит в `unknown` с `cancel_unconfirmed`. Это конечное состояние записи:
HostsKeeper прекращает наблюдение и не обновляет его позднее, даже если
удалённый процесс, возможно, завершился самостоятельно. `process_may_continue`
остаётся `true`; время ожидания после cancel не подтверждает остановку.
Неопределённая запись продолжает резервировать capacity до удаления по retention
(до 24 часов), что также не гарантирует завершение удалённого процесса.

```json
{ "run_id": "uuid" }
```

Это вход status/cancel. Вход wait:

```json
{
  "run_id": "uuid",
  "timeout_sec": 30,
  "stdout_cursor": "0",
  "stderr_cursor": "0",
  "max_chars": 16384
}
```

```json
{
  "run_id": "uuid",
  "request_id": "uuid",
  "session_id": "uuid",
  "script_id": "uuid",
  "state": "running",
  "accepted_at": "2026-11-17T10:00:00Z",
  "started_at": "2026-11-17T10:00:01Z",
  "updated_at": "2026-11-17T10:00:01Z",
  "completed_at": null,
  "exit_code": null,
  "error_code": null,
  "process_may_continue": true,
  "stdout_chars_retained": 12,
  "stderr_chars_retained": 0,
  "stdout_truncated": false,
  "stderr_truncated": false
}
```

`scripts_run_wait` также возвращает:

```json
{
  "stdout": { "cursor": "0", "data": "ready\n", "truncated": false },
  "stderr": { "cursor": "0", "data": "", "truncated": false },
  "wait_timed_out": false
}
```

Записи run хранятся в памяти процесса до 24 часов, максимум 100; при заполнении
лимита новые запуски отклоняются, активные записи не вытесняются.

States: `accepted`, `starting`, `running`, `cancel_requested`, `succeeded`,
`failed`, `cancelled`, `session_lost`, `execution_timed_out`, `unknown`,
`not_supported`. `succeeded` требует подтверждённого exit code 0; `failed` —
подтверждённого ненулевого exit code. В остальных состояниях `exit_code=null`.
`cancelled` означает подтверждённую остановку. При `session_lost` и
`execution_timed_out` `process_may_continue=true`; эти состояния не гарантируют,
что remote process завершён. Если timeout привёл к подтверждённой остановке,
возвращается `state="cancelled"`, `error_code="execution_timeout"` и
`exit_code=null`. Неподдерживаемый сценарий имеет state
`not_supported` либо безопасную ошибку до запуска.

stdout и stderr имеют отдельные cursors; текст и shell body не включаются в
run metadata. Сервер не добавляет body к stdout/stderr и не читает результат из
общего PTY; фактический удалённый вывод сохраняется как есть, даже если строка
совпала с фрагментом body. В общем session buffer эти потоки отображаются
в порядке чтения channel без отдельной маркировки stdout/stderr; запуск
помечается идентификатором и инициатором (`user`/`MCP client`), усечение
обозначается явно. UI-запуск сохранённого скрипта во встроенной вкладке
использует тот же exec-путь и формат transcript; поэтому он, как и MCP-запуск,
не наследует cwd и environment интерактивного shell. PuTTY остаётся внешним
путём. MCP-клиенту рекомендуется показывать запуск как
`Run script: <name>` со state (`accepted` не означает завершение), а результат
отдельно получать через `scripts_run_wait`; рендеринг tool-вызовов зависит от
клиента. На каждый поток удерживаются первые 131072 символа; последующий
вывод отбрасывается и отмечается `stdout_truncated` / `stderr_truncated`.
Внутри отдельного `stdout` / `stderr` объекта `truncated` означает, что после
текущего chunk остаются сохранённые данные для следующего cursor. Cursors —
десятичные смещения в символах; отсутствующий cursor равен `"0"`.
Для одного run действует максимум 600 секунд, один активный/неопределённый
запуск на сессию и восемь на процесс, до 100 хранимых записей (активные не
вытесняются). При любом из этих лимитов, включая заполненное хранилище записей,
старт отклоняется с `run_capacity`, без очереди; безопасное сообщение ошибки
различает причину и применимый предел.

Каждый вызов status/wait/cancel заново проверяет доступность исходной сессии в
scope текущего MCP access. Невалидный или недоступный `run_id` возвращает общий
`not_found`; raw token/app key не сохраняются в run record. Для этих
read-only/stop-запросов Approve не требуется; scripts_run всегда требует
Approve. Отзыв MCP доступа к исходной сессии блокирует доступ к её run-записям.

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
| `not_found` | Нет сессии/скрипта/run в scope. Для скрипта обновите `scripts_list`; host-скрипт требует открытую MCP-вкладку своего хоста |
| `disconnected` | SSH/PTY не live |
| `approve_required` | Approve выкл — write/run запрещены |
| `invalid_args` | Валидация входа; при сохранении скрипта — некорректный placeholder или объявления параметров |
| `missing_param` | Нет значения для используемого placeholder |
| `unknown_placeholder` | В body остался незакрытый/неизвестный `{{...}}` |
| `run_capacity` | Достигнут лимит одновременных запусков; запрос не поставлен в очередь |

## Чего нет в v1

- Tools для списка хостов/адресов/учёток (кроме Notes текущего MCP-хоста: `host_profile_*`)
- Открытие новой SSH-сессии силами ИИ
- Доступ к PuTTY/WinSCP окнам
- Выдача секретов «для отладки»
