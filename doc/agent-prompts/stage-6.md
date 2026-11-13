# Этап 6 — UI (connection manager)

Ты исполнитель **только этапа 6**. Launchers PuTTY/WinSCP — этап 7 (можно заглушки пунктов меню).

## Обязательное чтение

- `AGENTS.md`, `doc/ui-guidelines.md`, `doc/implementation-plan.md` → этап 6

## Сделать

1. Выбор стека UI (Tauri+web или FastAPI+static webview/browser) — зафиксировать в отчёте.
2. Layout: дерево слева + тулбар + вкладки + status bar (как ui-guidelines).
3. Unlock vault; CRUD Host/Address/Credential/Script; reveal secret локально.
4. Open: Host → Address+Credential → вкладка SSH.
5. Session chrome: alias, MCP ON/OFF, Copy URL, approve checkbox, Reconnect.
6. MCP connect/disconnect all; approve modal + countdown.
7. Статусы цветом в дереве/вкладках.

Терминал внутри вкладки — минимальный виджет; chrome — connection manager.

## Критерий приёмки

- [ ] Сценарий человек+MCP без CLI (unlock → open tab → MCP URL → write/approve).
- [ ] Layout не чат-центричный; alias виден на вкладке.

## Отчёт оркестратору

Сделано / стек UI / как запустить / скрин или описание экранов / отклонения.
