# HostsKeeper — краткий гид пользователя (v1 + PySide6)

## Запуск

```powershell
cd d:\HostsKeeper
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python -m hostskeeper
```

Откроется desktop-окно (PySide6) **без** диалога пароля. Вверху слева — список Vaults  
(пути в `%APPDATA%\HostsKeeper\settings.json`), внизу — Hosts/Scripts после подключения.

1. ПКМ по Vaults → **Add existing** / **Create new**, выберите файл.
2. Нажмите **Connect vault** → введите пароль (каждый раз заново).
3. Host/Script — через ПКМ по дереву; вкладка SSH — кнопка **+** у ярлыков вкладок.

Версия без GUI: `python -m hostskeeper --version`

## Типовой сценарий с ИИ

1. Создайте Host → Address → Credential (ключ/пароль) через ПКМ в дереве.
   Во вкладке **Notes** — Markdown-профиль хоста (ОС, пакеты, runtimes) для ИИ; переключатель **Preview** включает просмотр.
2. Выберите их → **+** на панели вкладок.
3. Включите **MCP** на вкладке. Один раз: **Options → Copy MCP config** → вставьте в Cursor `mcp.json`
   (`http://<ip>:8765/mcp?key=...`). Дальше ИИ: `session_list` → `session_attach(alias=…)`.
   В **Options** сверху — путь к `settings.json` (только просмотр): **Open Folder** (Explorer с выделением файла) и **Edit** (Notepad).
   **Change MCP Key** — новый app key (старый URL перестаёт работать); потом снова **Copy MCP config**.
4. Чтобы ИИ мог писать в терминал / запускать скрипты — включите **Approve** на вкладке
   (по умолчанию выкл: модель только читает вывод).
5. Вставьте URL в Cursor MCP / чат ассистенту.
6. ИИ видит alias через `session_info`, читает вывод; пишет команды только при включённом Approve.

## Терминал во вкладке

Вкладка — VT100-подобный виджет (pyte): цвета, `top`/`less`, стрелки/Ctrl+C, resize по размеру окна.  
Клик по области терминала — фокус для ввода (отдельной строки ввода нет).  
**Save log…** — сохранить полный scrollback в `.txt` (`alias-YYYYMMDD-HHMMSS.txt`). В файле может оказаться то, что уже было на экране (в т.ч. секреты из вывода команд).

## Важно

- Секреты и IP **не** отдаются через MCP — только alias/id/status и текст терминала.
- Reveal secret — только явная кнопка в UI.
- PuTTY/WinSCP — только для вас, без MCP.
- Launchers: пароль **не** в cmdline — PuTTY `-pwfile` (named pipe); WinSCP GUI — `/password=` + `/passwordsfromfiles` (named pipe). Предпочтительнее ключ.
- MCP HTTP слушает LAN (`0.0.0.0:8765` по умолчанию) — используйте в доверенной сети.
- На lab-хостах не гоняйте разрушительные команды.

## Остановка

Закройте окно HostsKeeper. Открытые SSH-сессии завершатся.
