# Чеклист регрессии (PySide6)

Автопрогон ядра Tab+MCP: `python scripts/check_tab_mcp_live.py` (при заданном `HOSTSKEEPER_TEST_SSH_KEY`).

- [x] `pip install -e ".[dev]"` и `pytest` — 24 passed
- [x] `python -m hostskeeper --version` → `HostsKeeper 0.1.0`
- [x] Open Tab / echo / reconnect (headless = тот же SessionManager, что Qt) — `check_tab_mcp_live.py`
- [x] Qt UI: Open Tab видно в вкладке, ввод с клавиатуры (ручной)
- [x] MCP On → URL; `session_info` без IP/ключей — auto
- [x] Approve off → write denied (`approve_required`); on → write в PTY — auto
- [x] Script create + run с `{{param}}` — auto
- [x] Disconnect / Reconnect, token тот же — auto
- [x] PuTTY и WinSCP (password via named pipe / GUI) — подтверждено человеком
- [x] Qt: MCP / Approve / Copy MCP config (тулбар) (ручной)
- [x] Lock vault очищает дерево и вкладки (ручной)
- [x] В ответах MCP нет password/private_key/address — auto

**Cursor по LAN:** ручная проверка человеком  
(`http://<safe-ip>:8765/mcp?key=...` из **Copy MCP config**).

Слияние в `main` — после ручных пунктов Qt + Cursor LAN.
