# Модель данных HostsKeeper v1

## Связи

```text
Group (kind=hosts|scripts, parent_id?, host_id?) 1──* Group
Group 1──* Host | Script | Note   (через group_id; null = корень дерева)

Host 1──* Address
Host 1──* Credential
Host 1──* Script|Note (host_id) + Group(kind=scripts, host_id)   — локальные скрипты/заметки хоста
Host ── defaults ──► Address?, Credential?

Script/Note.host_id=null — шаблон (дерево Scripts слева)
Script/Note.host_id=Host — только этого хоста (вкладка Scripts в Edit Host)

Удаление Group — рекурсивно удаляет всё содержимое (подгруппы + hosts/scripts/notes).

Session (runtime, не в vault):
  → snapshot выбора Host + Address + Credential
  → alias, mcp_enabled, token?, approve_enabled
  → target: tab | putty | winscp
```

## Host

| Поле | Тип | Описание |
|------|-----|----------|
| id | UUID | Первичный ключ |
| name | string | Отображаемое имя |
| description | string? | Короткое описание (вкладка Host) |
| profile | string? | Notes: свободный текст о хосте (ОС, пакеты, runtimes…); вкладка Notes |
| notes_preview | bool | UI: Preview на вкладке Notes (default false); в MCP не отдаётся |
| tags | string[] | Теги |
| default_address_id | UUID? | Адрес по умолчанию |
| default_credential_id | UUID? | Учётка по умолчанию |
| group_id | UUID? | Папка в дереве Hosts (null = корень) |
| created_at / updated_at | datetime | Служебные |

## Group

| Поле | Тип | Описание |
|------|-----|----------|
| id | UUID | Первичный ключ |
| name | string | Имя папки |
| kind | `hosts` \| `scripts` | В каком корне дерева |
| parent_id | UUID? | Родительская группа |
| host_id | UUID? | `null` = глобальное дерево; иначе папка скриптов хоста (`kind=scripts` only) |
| expanded | bool | UI: развёрнута ли папка (default true); в MCP не отдаётся |
| created_at / updated_at | datetime | Служебные |

Дополнительно в plaintext vault: `ui_tree.hosts_root_expanded` / `ui_tree.scripts_root_expanded` (bool, default true) — состояние корней Hosts/Scripts. Дерево Vaults (группы файлов) хранит expand в `%APPDATA%\HostsKeeper\settings.json` (`vault_tree_expanded`).

## Address

| Поле | Тип | Описание |
|------|-----|----------|
| id | UUID | Первичный ключ |
| host_id | UUID | Владелец |
| label | string? | Короткое имя («lan», «vpn») |
| host | string | IP или DNS |
| port | int | Порт SSH/SFTP (default 22) |
| description | string? | |
| tags | string[] | |
| knock_enabled | bool | Перед SSH/PuTTY/WinSCP выполнить port knock (default false) |
| knock_steps | `{port, protocol}[]` | Sequence; `protocol` = `tcp`\|`udp` (напр. UI: `4011,5022:udp,6033`) |
| knock_ports | int[] | Legacy (только порты); при чтении без `knock_steps` → все tcp |
| knock_delay_ms | int | Пауза между ударами (default 200) |
| knock_pause_ms | int | Пауза после sequence перед connect (default 300) |
| created_at / updated_at | datetime | |

Клиентский knock — только локально (не MCP). Sequence не отдавать через MCP/логи. Reconnect Tab повторяет knock. TCP = connect/SYN; UDP = пустой datagram.

## Credential

| Поле | Тип | Описание |
|------|-----|----------|
| id | UUID | Первичный ключ |
| host_id | UUID | Владелец |
| label | string? | Короткое имя |
| username | string | Логин |
| auth_type | `password` \| `key_pair` \| `openssh_config` | Способ аутентификации |
| password | secret? | Пароль (активен при `password`; может храниться и при других типах) |
| private_key | secret? | PEM/OpenSSH key (активен при `key_pair`; может храниться и при других типах) |
| passphrase | secret? | Пароль к ключу (для `key_pair`; может храниться и при других типах) |
| description | string? | |
| tags | string[] | |
| created_at / updated_at | datetime | |

Один Credential может одновременно держать последние `password` и `private_key`/`passphrase` для одного username: смена `auth_type` не затирает секреты неактивного способа. Для connect/launchers используется только активный тип.  
Ограничение при сохранении: `password` требует непустой password; `key_pair` — private_key; `openssh_config` — агент/`~/.ssh/config` (ранее сохранённые секреты остаются в vault).

**Важно:** поля secret никогда не сериализуются в MCP и в логи.

## Script

| Поле | Тип | Описание |
|------|-----|----------|
| id | UUID | Первичный ключ |
| name | string | Уникально в пределах `host_id` (шаблоны: `host_id=null`) |
| description | string? | |
| tags | string[] | |
| body | string | Shell-текст; целевой MCP run использует отдельный exec-channel, не общий PTY |
| parameters | Parameter[] | Описание подстановок |
| group_id | UUID? | Папка (тот же scope `host_id`, что у Script) |
| host_id | UUID? | `null` = шаблон; иначе скрипт хоста |
| mcp_enabled | bool | UI-чекбокс MCP; default false для новых UI-скриптов; legacy-скрипты без поля сохраняют видимость (true) |
| created_at / updated_at | datetime | |

MCP видит только скрипты с `mcp_enabled=true`: шаблоны доступны всегда, host-local — только при открытой MCP-вкладке этого хоста. Скрипты, созданные через MCP, сразу получают `mcp_enabled=true`; `scripts_update` не меняет этот флаг.

Удаление Host каскадно удаляет его Address/Credential/Script/Note и host-группы Scripts.

## Note

Markdown-лист в деревьях Scripts (не путать с Host → Notes / `profile`).

| Поле | Тип | Описание |
|------|-----|----------|
| id | UUID | Первичный ключ |
| name | string | Уникально в пределах `host_id` |
| body | string | Markdown |
| group_id | UUID? | Та же папка scripts, что у Script |
| host_id | UUID? | `null` = шаблон; иначе заметка хоста |
| mcp_enabled | bool | UI-чекбокс; default false (человек); create через MCP всегда true |
| preview | bool | UI: Markdown Preview (default false); в MCP не отдаётся |
| created_at / updated_at | datetime | |

MCP `notes_*` видит только `mcp_enabled=true` (шаблоны + host-local при открытой MCP-вкладке). Approve не требуется. `notes_update` не меняет `mcp_enabled`.

### Parameter

| Поле | Тип | Описание |
|------|-----|----------|
| name | string | Имя для `{{name}}` |
| description | string? | Подсказка для ИИ/человека |
| required | bool | Обязательность |
| default | string? | Значение по умолчанию (MCP / обычный Run) |
| user_value | secret? | Человеческое значение для локального Run (PuTTY); при создании параметра копируется из `default`, дальше только руками; в MCP не отдаётся |

Подстановка: все вхождения `{{name}}` в `body` заменяются значениями.  
- MCP `scripts_run` / обычный Run: `params` → иначе `default` → иначе ошибка для required.  
- Run dialog с **Use user values**: только `user_value` (пустая строка допустима; `null`/отсутствие при использовании в body — ошибка до launch/Copy); цель только PuTTY (+ Copy в буфер).  
Неразрешённые плейсхолдеры — ошибка (не молчаливая вставка пустоты).

## Session (runtime)

Не сохраняется в vault как секретная сессия; при необходимости позже — только UI-предпочтения.

| Поле | Тип | Описание |
|------|-----|----------|
| id | UUID | Внутренний id вкладки/сессии |
| alias | string | Человекочитаемое имя (шапка + MCP) |
| host_id / address_id / credential_id | UUID | Снимок выбора |
| target | enum | `tab` \| `putty` \| `winscp` |
| status | enum | `connecting` \| `live` \| `disconnected` \| `closed` |
| mcp_enabled | bool | Кнопка MCP |
| mcp_token | secret? | Per-tab token (если mcp_enabled) |
| mcp_client_connected | bool | Занят ли слот клиента |
| approve_enabled | bool | Чекбокс Approve: MCP write/run (default false) |
| created_at | datetime | |

Для `target=putty|winscp` поля MCP не используются (или всегда `mcp_enabled=false`).

### Реализация runtime (этап 2)

- API: `hostskeeper.session.SessionManager` + `SessionInfo` (без address/username/secrets в `repr`).
- Транспорт вкладки: **Paramiko** interactive shell; вывод в `OutputBuffer` с cursor.
- Alias auto: `{host.name}-{username}-{n}`.

### ScriptRun (runtime; не сохраняется в vault)

Целевая runtime-запись состояния MCP-запуска в памяти процесса (lifecycle ещё
не подключён к текущему MCP `scripts_run`; текущее поведение описано в
`doc/mcp-api.md`). Запись привязана к исходной
сессии и скрипту; origin фиксирует только тип MCP-доступа, не token или app key.
Доступ к записи проверяется повторным разрешением `session_id` в текущем
клиентском scope.

| Поле | Тип | Описание |
|------|-----|----------|
| run_id | UUID | Идентификатор запуска |
| request_id | UUID | Идемпотентный ключ от MCP-клиента, уникальный для намерения в пределах сессии |
| session_id / script_id | UUID | Исходные объекты |
| origin | enum | `stdio` \| `http_gateway` \| `http_legacy`; не является credential |
| state | enum | `accepted` \| `starting` \| `running` \| `cancel_requested` \| `succeeded` \| `failed` \| `cancelled` \| `session_lost` \| `execution_timed_out` \| `unknown` \| `not_supported` |
| accepted_at / started_at / updated_at | datetime | UTC-время принятия, начала и последнего изменения |
| completed_at | datetime? | Только если завершение процесса подтверждено |
| exit_code | int? | Только для `succeeded` (0) и `failed` (ненулевой) |
| error_code | enum? | Стабильный безопасный код; без сырых SSH/OS сообщений |
| stdout / stderr metadata | object | Число удержанных символов и `truncated`; содержимое читается раздельно по cursors |

`session_lost` и `execution_timed_out` не подтверждают остановку процесса; status
ответ содержит `process_may_continue=true`. Если executor подтвердил остановку
из-за execution timeout, state становится `cancelled` с `error_code`=`execution_timeout`
и без exit code. Утрата связи, timeout или неизвестный результат никогда не
получают выдуманный exit code. Status/wait/cancel повторно проверяют, что
исходная сессия доступна в scope запроса; знание `run_id` само по себе не даёт
доступа.

Повтор с тем же `request_id` и `session_id` возвращает исходную запись, не
запуская скрипт повторно; новый запуск требует нового request id. Идемпотентность
действует, пока запись сохранена (до 24 часов). Run records и output существуют
только в памяти текущего процесса. Записи удерживаются до 24 часов, максимум
100; активные не вытесняются. При заполнении лимита новые запуски отклоняются до
освобождения места. На каждый
stdout/stderr stream удерживается до 131072 символов с начала вывода; последующий
текст отбрасывается и отмечается `truncated=true`. Перезапуск HostsKeeper удаляет
run records. `error_code` может содержать только стабильные коды (`start_failed`,
`session_lost`, `execution_timeout`, `cancel_unconfirmed`, `not_supported`,
`unknown`), но не raw exception text.

## Что отдаётся наружу через MCP

| Разрешено | Запрещено |
|-----------|-----------|
| session id / alias / status | host, address, port, username |
| вывод PTY (новые строки) | password, key, passphrase |
| метаданные скриптов и body | пути на диске сейфа, содержимое vault blob |
| parameters без `user_value` | `user_value` параметров скрипта |
| ошибки `disconnected` / `approve_required` | любые raw credential |
| `screen_tail` / `alt_screen` (из UI) | — |

## Хранение

### Формат файла vault (этап 1)

- Один бинарный файл (расширение `.vault` по соглашению).
- Оболочка: magic `HSVAULT1` + salt (16) + nonce (12) + ciphertext.
- KDF: **Scrypt** (n=2¹⁴, r=8, p=1) → 32-byte key из пароля приложения.
- AEAD: **AES-256-GCM** (AAD = magic).
- Plaintext: JSON UTF-8, `version: 1`, словари `hosts` / `addresses` / `credentials` / `scripts` / `groups` (ключ = id UUID; `groups` опционален для старых vault), опционально `ui_tree` (expand корней).
- Runtime-сессии и MCP token — только в памяти процесса (не в vault); после рестарта MCP нужно включать заново.

Класс API: `hostskeeper.vault.Vault` (`create` / `unlock` / `lock` / `save` + CRUD).
