# HostsKeeper — документация

HostsKeeper — локальный Windows-сейф параметров подключений к хостам, библиотека shell-скриптов и встроенный MCP-сервер для удалённого ИИ-ассистента.

ИИ не получает секреты и адреса. Работает только с явно открытыми человеком вкладками терминала (по token) и с каталогом скриптов.

## Содержание

| Документ | Описание |
|----------|----------|
| [requirements.md](requirements.md) | Требования и принятые решения |
| [architecture.md](architecture.md) | Архитектура системы |
| [data-model.md](data-model.md) | Модель данных vault |
| [mcp-api.md](mcp-api.md) | Контракт MCP tools |
| [implementation-plan.md](implementation-plan.md) | План реализации по этапам |
| [ui-guidelines.md](ui-guidelines.md) | Целевой стиль UI (connection manager) |
| [pyside6-migration.md](pyside6-migration.md) | План перехода UI с FastAPI/static на PySide6 (этапы 9–14) |
| [orchestration.md](orchestration.md) | Оркестрация этапов и эскалации |
| [agent-prompts/](agent-prompts/README.md) | Промпты исполнителей по этапам 0–14 |
| [dev-setup.md](dev-setup.md) | Подготовка Python/venv/PuTTY/WinSCP |
| [user-guide.md](user-guide.md) | Краткий гид пользователя |
| [regression-checklist.md](regression-checklist.md) | Чеклист регрессии v1 |

## Кратко о продукте

- **Кто:** один пользователь + удалённый ИИ через MCP.
- **Где:** приложение на Windows («ПК-сейф»).
- **Что хранит:** Host, Address, Credential, Script — в зашифрованном vault (пароль при старте).
- **Сессии:** открывает только человек (вкладка UI / PuTTY / WinSCP).
- **MCP:** только вкладки UI с включённым доступом; read/subscribe/write + CRUD/run скриптов.
- **Не делаем в v1:** облако, Multiplayer, агент на целевых хостах, non-interactive SSH, backup vault, импорт Termius.
