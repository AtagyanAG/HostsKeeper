# Переход UI на PySide6

Статус: **этапы 9–14 реализованы** (desktop PySide6). Ручная регрессия — [regression-checklist.md](regression-checklist.md).  
Контекст: v1 (этапы 0–8) закрыт на FastAPI + static web; по регрессии UX признан неудобным для класса connection manager (дерево + тулбар + вкладки). Целевой стек презентации — **PySide6** (LGPL), не PyQt6.

Связанные документы: [architecture.md](architecture.md), [ui-guidelines.md](ui-guidelines.md), [implementation-plan.md](implementation-plan.md), [requirements.md](requirements.md).

## Зачем

| Проблема web UI | Ожидание от native Qt |
|-----------------|------------------------|
| Браузерный chrome, чужой focus/hotkeys | Обычное desktop-окно Windows |
| Polling HTTP → лаги терминала / approve | Сигналы/слоты к SessionManager |
| Layout «сайт поверх API» | Нативные `QTreeWidget`, `QToolBar`, `QTabWidget`, диалоги |
| Два процесса внимания (браузер + сервер) | Один процесс HostsKeeper |

## Что не трогаем

Ядро остаётся Python-пакетом `hostskeeper.*`:

- `vault` — Scrypt + AES-GCM, CRUD сущностей
- `session` — Paramiko, буфер, alias, reconnect, Approve checkbox
- `mcp` — stdio + HTTP Streamable (token, 1 client); контракт [mcp-api.md](mcp-api.md)
- `launchers` — PuTTY / WinSCP (+ OpenSSH→`.ppk`)

Инварианты MCP/секретов **без изменений**. HTTP MCP для Cursor по LAN **сохраняется** (отдельный uvicorn-поток или тот же Starlette ASGI).

## Целевая архитектура

```text
┌──────────────── HostsKeeper.exe / python -m hostskeeper ────────────────┐
│  PySide6 MainWindow (дерево · тулбар · вкладки · status)             │
│       │ QObject adapters / signals                                   │
│       ▼                                                              │
│  App Core (существующий: Vault, SessionManager, …)                   │
│       ├─ MCP HTTP thread (LAN token) ──► Cursor                      │
│       ├─ MCP stdio (опционально отдельный вход)                      │
│       └─ Launchers (subprocess, human-only)                          │
└──────────────────────────────────────────────────────────────────────┘
```

- Слой `hostskeeper.api` (REST для браузера) после этапа 14 **убирается из UX**; smoke-тесты либо переводятся на прямой core, либо временно держат API за флагом.
- Статика `hostskeeper/ui/static/*` удаляется после паритета Qt.
- Новый пакет: `hostskeeper.desktop` (или `hostskeeper.qt`) — только презентация + тонкие адаптеры.

## Принципы миграции

1. Один этап за раз (`doc/agent-prompts/stage-N.md`); не начинать N+1.
2. Паритет поведения с чеклистом [regression-checklist.md](regression-checklist.md), не «новый продукт».
3. Секреты не в логах/MCP/`repr`; reveal — только Qt-диалог по явной кнопке.
4. Approve: чекбокс (default выкл = MCP read-only; вкл = write/run без модалки).
5. Терминал UI — **pyte** + `TerminalWidget` (цвета, cursor, resize PTY, клавиши). MCP по-прежнему сырой текст.
6. Пока Qt не закрыл сценарий — web UI можно оставить как fallback (`python -m hostskeeper.api`), без развития фич.

## Этапы 9–14

### Этап 9 — Каркас PySide6 + unlock

**Результат:** окно приложения, unlock vault, пустой Royal-layout.

- Зависимость `PySide6` в `pyproject.toml` (optional extra `desktop` допустим).
- `QMainWindow`: toolbar / left dock tree (заглушка) / central tabs (пусто) / status bar.
- Диалог unlock → `Vault.unlock` через существующий core/`AppState`.
- Точка входа: `python -m hostskeeper` → Qt (или явный `--ui qt`); web API — `--ui web`.
- MCP HTTP стартует как сейчас (фон), без привязки к браузеру.

**Критерий:** после unlock видно главное окно; lock очищает чувствительное состояние; pytest на non-UI core зелёный.

### Этап 10 — Дерево + CRUD properties

**Результат:** Hosts/Scripts в дереве; New/Edit/Delete; reveal secret.

- `QTreeWidget` / `QTreeView` по [ui-guidelines.md](ui-guidelines.md).
- Модальные property-формы (Host, Address, Credential, Script).
- Контекстное меню: Edit / Open… (Open Tab — заглушка до 11).
- Поиск/фильтр по дереву.

**Критерий:** полный CRUD без браузера; секреты не в status bar; persist после restart процесса.

### Этап 11 — SSH-вкладки + терминал

**Результат:** Open Tab → alias tab → read/write PTY в Qt.

- Открытие сессии через `SessionManager`.
- Вкладка: chrome (alias, status) + область вывода/ввода.
- Подписка на буфер: Qt signals / `QTimer` poll к cursor буфера (без HTTP UI).
- Reconnect / Disconnect / Close tab.

**Критерий:** echo в UI; write с клавиатуры доходит в lab SSH; статусы live/disconnected/closed.

### Этап 12 — MCP chrome + Approve

**Результат:** MCP ON/OFF, Copy URL, Enable/Disable all; Approve checkbox.

- Per-tab token URL как в web UI.
- Approve: standing permission для write/run (без модалки).
- Status bar: MCP listening / client connected (без секретов).

**Критерий:** Cursor (или `scripts/check_mcp_live.py`) write при Approve off → `approve_required`; при on → в PTY; HTTP token scope без изменений.

### Этап 13 — Launchers в Qt

**Результат:** PuTTY / WinSCP из тулбара и контекстного меню.

- Вызов существующих `launch_putty` / `launch_winscp`.
- Без MCP-сессий для launcher-окон.

**Критерий:** как этап 7, но из Qt; `.ppk` путь без регрессий.

### Этап 14 — Вывод web UI + документация

**Результат:** Qt — основной UX; docs и чеклист обновлены.

- Удалить/архивировать static UI; убрать FastAPI UI-роуты (MCP HTTP оставить).
- Обновить `user-guide.md`, `regression-checklist.md`, `architecture.md`, `dev-setup.md`.
- README: запуск desktop; опционально отметить web как retired.

**Критерий:** чеклист пройден на PySide6; автотесты core/MCP зелёные; нет обязательного браузера для продукта.

## Порядок

```text
9 Scaffold+unlock
 └─ 10 Tree+CRUD
      └─ 11 Tabs+SSH UI
           ├─ 12 MCP+Approve UI
           └─ 13 Launchers Qt
                └─ 14 Retire web UI + docs
```

Этапы 12 и 13 можно частично параллелить после 11, если нет конфликта по файлам окна.

## Тестирование

| Слой | Как |
|------|-----|
| Core / MCP | Существующий `pytest` — не ломать |
| Qt логика | Тонкие unit-тесты адаптеров без показа окна где возможно |
| UI smoke | Ручной прогон по [regression-checklist.md](regression-checklist.md) |
| Live MCP | `scripts/check_mcp_live.py` + Cursor LAN (человек) |

Авто-GUI (pytest-qt) — по желанию с этапа 11; не блокер паритета.

## Риски

| Риск | Смягчение |
|------|-----------|
| Потоки: Paramiko + uvicorn + Qt main thread | I/O вне GUI-потока; в UI только signals/`QMetaObject.invokeMethod` |
| Зависимость Qt в CI без дисплея | Extra `desktop`; CI гоняет core без PySide6 |
| Дублирование web+Qt | Заморозка web-фич с этапа 9; паритет → удаление |
| Тяжёлый терминал | Сознательный минимализм до post-v1 |

## Вне scope этого перехода

- Облако, Multiplayer, агент на хостах, vault backup, импорт Termius
- Смена MCP-контракта или vault-формата
- Полноценный VT100/xterm.js-клон
- Переписывание launchers/MCP «с нуля»

## Решение по лицензии

**PySide6 (Qt for Python, LGPL)** — выбран вместо PyQt6 (GPL/коммерческая), чтобы не тянуть GPL на весь продукт без отдельного решения владельца.
