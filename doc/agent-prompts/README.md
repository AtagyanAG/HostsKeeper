# Промпты исполнителей по этапам

Оркестратор подставляет нужный файл как ТЗ. Источник критериев: [../implementation-plan.md](../implementation-plan.md).

| Этап | Файл | Кратко |
|------|------|--------|
| 0 | [stage-0.md](stage-0.md) | Каркас Python-пакета |
| 1 | [stage-1.md](stage-1.md) | Vault |
| 2 | [stage-2.md](stage-2.md) | Session / SSH headless |
| 3 | [stage-3.md](stage-3.md) | MCP sessions (stdio → HTTP) |
| 4 | [stage-4.md](stage-4.md) | Approve |
| 5 | [stage-5.md](stage-5.md) | Scripts MCP |
| 6 | [stage-6.md](stage-6.md) | UI connection manager (FastAPI + static, временный) |
| 7 | [stage-7.md](stage-7.md) | PuTTY / WinSCP launchers |
| 8 | [stage-8.md](stage-8.md) | Стабилизация v1 |
| 9 | [stage-9.md](stage-9.md) | PySide6 каркас + unlock |
| 10 | [stage-10.md](stage-10.md) | Дерево + CRUD properties |
| 11 | [stage-11.md](stage-11.md) | SSH-вкладки + терминал |
| 12 | [stage-12.md](stage-12.md) | MCP chrome + Approve |
| 13 | [stage-13.md](stage-13.md) | Launchers в Qt |
| 14 | [stage-14.md](stage-14.md) | Вывод web UI + docs |

План миграции UI: [../pyside6-migration.md](../pyside6-migration.md).  
Общий префикс для любого этапа — см. `AGENTS.md` (инварианты + обязательное чтение).
