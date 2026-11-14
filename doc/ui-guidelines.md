# UI Guidelines — connection manager

**Цель:** визуальный и композиционный стиль *polished connection manager* для IT: дерево объектов, тулбар, вкладки сессий — без чат-центричного layout.

HostsKeeper — свой продукт (vault + MCP). **Класс интерфейса:** дерево объектов слева, лента/тулбар сверху, вкладки сессий в центре, статусная строка снизу.

## Паттерны UI

| Паттерн | Как применять в HostsKeeper |
|---------|---------------------------|
| Workspace admin-tool | Плотная, спокойная рабочая среда, не «маркетинговый» лендинг и не чат-UI |
| Левое дерево навигации | Иерархия: Hosts → Addresses/Credentials; отдельно Scripts; индикаторы статуса |
| Вкладки подключений | Центр = активные сессии; вкладка показывает **alias** (+ иконка типа: SSH tab / PuTTY / WinSCP) |
| Тулбар / ribbon-команды | Компактная лента: Connect vault, Close All Tabs, Options — без перегруза |
| Статусы цветом | Точки/бейджи: live / disconnected / MCP on / Approve on |
| Поиск по дереву | Фильтр хостов/скриптов в шапке левой панели |
| Status bar | Краткий лог/статус MCP (listening, клиент connected), без секретов |
| Светлая рабочая область | Светло-серый/белый контент; тёмный или нейтральный chrome (title/sidebar) допустим |
| Типографика | Мелкий читаемый sans-serif, высокая информационная плотность |

Дух UI: *customizable workspace, dock panels, ribbon commands and connection tabs* — «всё в деталях», чистый профессиональный вид.

## Что сознательно упрощаем в v1

- Полный Fluent Ribbon и произвольные dock-layout — **не обязательны**; достаточно фиксированного 3-зонного layout.
- Dashboards / performance / RDP / VNC / Hyper-V — **вне scope**.
- Темы и глубокая кастомизация workspace — позже.
- Терминал во вкладке — **функциональный минимализм** (совпадение с MCP), обрамление вкладки — в стиле connection manager.

## Композиция главного окна (целевая)

```text
┌─ HostsKeeper ──────────────────────────────────────────────┐
│ [Ribbon / Toolbar: Open ▾ Tab|PuTTY|WinSCP | MCP | …]   │
├──────────────┬───────────────────────────────────────────┤
│ Search…      │ Tabs: prod-web-1 │ lab-1 │ …             │
│              ├───────────────────────────────────────────┤
│ ▸ Hosts      │                                           │
│   Host A     │   Terminal / session content              │
│   Host B     │   (шапка вкладки: alias · MCP · approve)  │
│ ▸ Scripts    │                                           │
│   script-1   │                                           │
│              │                                           │
├──────────────┴───────────────────────────────────────────┤
│ status: vault unlocked · MCP :8787 · client:1            │
└──────────────────────────────────────────────────────────┘
```

### Левая панель

- Дерево **Hosts** (дети: addresses/credentials как подчиненные узлы или через properties).
- Раздел **Scripts**.
- Опционально **Open sessions** (alias + status) — удобно прыгать на вкладку.
- Иконки типа объекта; цвет статуса у открытых сессий.
- Контекстное меню: Open in Tab / PuTTY / WinSCP, Edit, Show secret (credentials).

### Центр

- Tab strip с alias.
- Активная вкладка SSH: область терминала + тонкая session chrome (MCP, Approve, Reconnect / Disconnect / Close).
- Вкладки launcher (если показываем факт запуска) — без PTY; либо только внешний процесс без вкладки (предпочтение v1: вкладка только для встроенного SSH).

### Лента / тулбар

Группы (логически, даже если UI — один toolbar):

1. **Vault** — Lock  
2. **Connect** — Open Tab / PuTTY / WinSCP  
3. **Session** — Reconnect / Disconnect / Close  
4. **Close All Tabs** — закрыть все SSH-вкладки (с подтверждением); MCP — per-tab; Copy MCP config — в Options  
5. **Edit** — New Host / Address / Credential / Script  

### Диалоги

- Unlock vault — простой модальный, без декоративного шума.
- Approve — чекбокс на chrome: вкл = MCP write/run; выкл = только чтение.
- Редакторы сущностей — property-style формы (как в connection managers), не wizard-лендинги.
- «Показать секрет» — явное действие, короткоживущее раскрытие в UI.

## Визуальный язык

- Спокойная нейтральная палитра (серые поверхности, один акцентный цвет статуса/active tab).
- Плоские панели, тонкие разделители, без «neon/glass/AI-purple».
- Active tab — чёткий индикатор (например цветная полоска сверху вкладки).
- Иконки: простые glyph/protocol, единообразный размер.

## Соответствие требованиям HostsKeeper

| Требование продукта | Отражение в UI |
|---------------------|----------------|
| Секреты не в MCP | В UI — отдельная кнопка reveal; в status/MCP URL — только token/alias |
| Сессию открывает человек | Connect только из дерева/ленты |
| Alias в шапке | Tab title + session chrome |
| MCP per tab | Toggle на вкладке; Copy MCP config / Change MCP Key в Options |
| Approve per session | Checkbox на chrome вкладки (standing permission) |
| Скрипты без UI-форм params | Редактор body/`{{params}}` в properties; запуск из UI опционален в v1 |

## Стек UI

- **Стек:** native **PySide6** (не PyQt6) — см. [pyside6-migration.md](pyside6-migration.md).
- Браузерный FastAPI/static UI (этап 6) **выведен** на этапе 14.

## Этап реализации

Композиция реализована в `hostskeeper.desktop` (этапы 9–14).

## Анти-паттерны

- Чат-центричный layout
- Карточки-маркетинг вместо дерева
- Только тёмный «IDE-клоун» без читаемой иерархии объектов
- Прятать Connect/MCP в глубокие меню
- Скрывать alias сессии
