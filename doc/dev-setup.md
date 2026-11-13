# Подготовка среды разработчика (Windows)

Чеклист перед этапом 0 и далее. Виртуальное окружение `.venv/` в git не коммитится.

## Статус на машине сейфа

| Компонент | Требование | Статус подготовки |
|-----------|------------|-------------------|
| Python | ≥ 3.11 (целевой 3.12) | 3.12.x → `.venv` |
| pip / setuptools / wheel | актуальные в venv | через `pip install -e ".[dev]"` |
| Git | да | установлен |
| OpenSSH Client (`ssh`) | для ручных проверок | обычно `C:\Windows\System32\OpenSSH\ssh.exe` |
| PuTTY | этап 7 (можно заранее) | типично `C:\Program Files\PuTTY\putty.exe` |
| WinSCP | этап 7 (можно заранее) | `%LOCALAPPDATA%\Programs\WinSCP\WinSCP.exe` |
| PySide6 | desktop UI | через `pip install -e ".[dev]"` |
| Тестовый SSH-хост | опционально, этап 2+ | свой lab; см. переменные ниже (ключ **вне** репо) |

## Активация venv

```powershell
cd <path-to-HostsKeeper>
.\.venv\Scripts\Activate.ps1
python --version
```

Если ExecutionPolicy блокирует скрипт:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Либо без активации: `.\.venv\Scripts\python.exe …`

## Установка пакета

```powershell
pip install -e ".[dev]"
python -m hostskeeper --version
pytest
python -m hostskeeper
```

Откроется desktop (PySide6): unlock vault, дерево Hosts/Scripts, вкладки SSH.

## Сборка HostsKeeper.exe (один файл)

```powershell
cd <path-to-HostsKeeper>
.\.venv\Scripts\Activate.ps1
.\scripts\build_exe.ps1
```

Результат: `dist\HostsKeeper.exe` (PyInstaller `--onefile`, без консоли; ~60 MB без QtWebEngine).  
Spec: `packaging/HostsKeeper.spec` (иконка: `src/hostskeeper/resources/hostskeeper.ico`).  
Пересобрать иконку: `pip install pillow` → `python scripts/generate_app_icon.py`.  
Зависимости сборки: `pip install -e ".[packaging]"`.

Перед пересборкой закройте запущенный `HostsKeeper.exe` (иначе WinError 5 на запись).  
Проверка: запуск exe → unlock → Open Tab → MCP / Copy MCP config.  
Первый старт onefile медленнее (распаковка во temp). SmartScreen может ругаться на неподписанный бинарник.

## Интеграционный SSH (опционально)

Живые SSH-тесты (`tests/test_session_ssh_integration.py` и др.) **пропускаются**, пока не задан ключ. Ключ и адрес lab **не** хранятся в git.

```powershell
$env:HOSTSKEEPER_TEST_SSH_HOST = "192.0.2.10"   # ваш lab host
$env:HOSTSKEEPER_TEST_SSH_PORT = "22"
$env:HOSTSKEEPER_TEST_SSH_USER = "labuser"
$env:HOSTSKEEPER_TEST_SSH_KEY  = "C:\path\to\id_ed25519"   # обязательно для live-тестов
pytest
```

На lab-хосте только безопасные команды (`echo` / `whoami`); учётка без sudo.

## Пути launchers

- PuTTY: обычно `C:\Program Files\PuTTY\putty.exe`
- WinSCP: обычно `%LOCALAPPDATA%\Programs\WinSCP\WinSCP.exe`

В настройках приложения пути конфигурируемы — не хардкодить только Program Files.
