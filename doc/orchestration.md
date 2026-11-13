# Оркестрация реализации

## Статус подготовки

- [x] Документация продукта в `doc/`
- [x] `AGENTS.md` + `.cursor/rules/`
- [x] Промпты этапов в `doc/agent-prompts/`
- [x] Среда: `.venv` (Python 3.12), PuTTY, WinSCP — см. [dev-setup.md](dev-setup.md)
- [ ] Тестовый SSH-хост — желательно до этапа 2
- [x] Этап 0 — каркас Python
- [x] Этап 1 — vault
- [x] Этап 2 — Session/SSH (Paramiko, optional lab via env)
- [x] Этап 3 — MCP sessions (stdio tools + HTTP token)
- [x] Этап 4 — Approve
- [x] Этап 5 — Scripts MCP
- [x] Этап 6 — UI (FastAPI + static, connection manager; временный)
- [x] Этап 7 — Launchers PuTTY/WinSCP
- [x] Этап 8 — Стабилизация (docs + checklist; Cursor LAN — эскалация)
- [x] Этап 9 — PySide6 каркас + unlock (`feature/pyside6-ui`)
- [x] Этап 10 — дерево + CRUD (`feature/pyside6-ui`)
- [x] Этап 11 — SSH-вкладки + терминал (`feature/pyside6-ui`)
- [x] Этап 12 — MCP chrome + Approve (`feature/pyside6-ui`)
- [x] Этап 13 — Launchers в Qt (`feature/pyside6-ui`)
- [x] Этап 14 — вывод web UI + docs (`feature/pyside6-ui`; merge в main после UI-приёмки)

## Цикл оркестратора

```text
команда на этап N
  → исполнитель по doc/agent-prompts/stage-N.md
  → проверка критерия (implementation-plan + промпт)
  → сомнение? → эскалация человеку → стоп
  → ок? → локальный коммит "Stage N: …"
  → этап N+1 (если не запрошена пауза)
```

## Эскалация человеку

- Нет решения в `doc/` (выбор технологии с долгими последствиями).
- Критерий этапа выполнен формально, но поведение рискованное (секреты, MCP scope).
- Нужен реальный хост / Cursor MCP / LAN с вашей стороны.
- Конфликт двух документов или промпта с планом.

## Коммиты

- Локальные, по одному на принятый этап (и отдельно prep-коммит агентских артефактов при необходимости).
- Push — только по явной просьбе человека.
