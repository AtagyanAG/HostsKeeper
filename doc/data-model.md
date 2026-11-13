# Модель данных HostsKeeper v1

## Связи

```text
Group (kind=hosts|scripts, parent_id?, host_id?) 1──* Group
Group 1──* Host | Script   (через group_id; null = корень дерева)

Host 1──* Address
Host 1──* Credential
Host 1──* Script (host_id) + Group(kind=scripts, host_id)   — локальные скрипты хоста
Host ── defaults ──► Address?, Credential?

Script.host_id=null — шаблон (дерево Scripts слева)
Script.host_id=Host — скрипт только этого хоста (вкладка Scripts в Edit Host)

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
| created_at / updated_at | datetime | Служебные |

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
| body | string | Shell-текст для вставки в PTY |
| parameters | Parameter[] | Описание подстановок |
| group_id | UUID? | Папка (тот же scope `host_id`, что у Script) |
| host_id | UUID? | `null` = шаблон; иначе скрипт хоста |
| created_at / updated_at | datetime | |

Удаление Host каскадно удаляет его Address/Credential/Script и host-группы Scripts.

### Parameter

| Поле | Тип | Описание |
|------|-----|----------|
| name | string | Имя для `{{name}}` |
| description | string? | Подсказка для ИИ/человека |
| required | bool | Обязательность |
| default | string? | Значение по умолчанию |

Подстановка: все вхождения `{{name}}` в `body` заменяются значениями при `scripts_run`. Неразрешённые плейсхолдеры — ошибка (не молчаливая вставка пустоты).

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

## Что отдаётся наружу через MCP

| Разрешено | Запрещено |
|-----------|-----------|
| session id / alias / status | host, address, port, username |
| вывод PTY (новые строки) | password, key, passphrase |
| метаданные скриптов и body | пути на диске сейфа, содержимое vault blob |
| ошибки `disconnected` / `approve_required` | любые raw credential |
| `screen_tail` / `alt_screen` (из UI) | — |

## Хранение

### Формат файла vault (этап 1)

- Один бинарный файл (расширение `.vault` по соглашению).
- Оболочка: magic `HSVAULT1` + salt (16) + nonce (12) + ciphertext.
- KDF: **Scrypt** (n=2¹⁴, r=8, p=1) → 32-byte key из пароля приложения.
- AEAD: **AES-256-GCM** (AAD = magic).
- Plaintext: JSON UTF-8, `version: 1`, словари `hosts` / `addresses` / `credentials` / `scripts` / `groups` (ключ = id UUID; `groups` опционален для старых vault).
- Runtime-сессии и MCP token — только в памяти процесса (не в vault); после рестарта MCP нужно включать заново.

Класс API: `hostskeeper.vault.Vault` (`create` / `unlock` / `lock` / `save` + CRUD).
