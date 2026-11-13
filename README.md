# HostsKeeper

Локальный Windows-сейф параметров подключений к хостам, библиотека shell-скриптов и встроенный MCP-сервер для удалённого ИИ.

Секреты остаются на ПК-сейфе. ИИ получает доступ только к явно открытым вкладкам терминала и к каталогу скриптов.

**Лицензия:** [MIT](LICENSE). Сторонние зависимости — см. [NOTICE](NOTICE).

HostsKeeper **не аффилирован** с авторами PuTTY, WinSCP или иных упомянутых в UI/доках внешних продуктов; при наличии они запускаются как уже установленные программы на машине пользователя и в этот репозиторий не входят.

## Документация

См. каталог [doc/](doc/README.md):

- [Требования](doc/requirements.md)
- [Архитектура](doc/architecture.md)
- [Модель данных](doc/data-model.md)
- [Контракт MCP](doc/mcp-api.md)
- [План реализации](doc/implementation-plan.md)
- [UI Guidelines (connection manager)](doc/ui-guidelines.md)
- [Миграция UI → PySide6](doc/pyside6-migration.md)
- [Оркестрация](doc/orchestration.md)
- [Промпты агентов](doc/agent-prompts/README.md)
- [Подготовка среды](doc/dev-setup.md)
- [Гид пользователя](doc/user-guide.md)
- [Чеклист регрессии](doc/regression-checklist.md)

Правила для Cursor: [`AGENTS.md`](AGENTS.md), `.cursor/rules/`.

## Development

```powershell
cd <path-to-HostsKeeper>
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python -m hostskeeper --version
pytest
python -m hostskeeper
```

UI: desktop PySide6 (`python -m hostskeeper`).  
MCP HTTP (после unlock): `http://<host>:8765/mcp?key=<app-key>` — **Copy MCP config** в тулбаре.

Сборка одного exe: `.\scripts\build_exe.ps1` → `dist\HostsKeeper.exe` (см. `doc/dev-setup.md`).

Опциональные live-SSH тесты: задайте `HOSTSKEEPER_TEST_SSH_KEY` (и при необходимости host/user) — см. [dev-setup.md](doc/dev-setup.md). Не коммитьте vault, ключи и `.env`.

## Статус

Ядро (этапы 0–8) и desktop PySide6 (этапы 9–14) в основной ветке. Регрессия: [doc/regression-checklist.md](doc/regression-checklist.md).
