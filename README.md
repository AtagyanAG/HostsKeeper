# HostsKeeper

**Local credential vault + human-gated SSH tabs for MCP/AI — not a generic remote desktop.**

HostsKeeper keeps host credentials and shell scripts on your Windows PC. **You** open SSH sessions in tabs. An AI client (e.g. Cursor) attaches only to tabs you enable for MCP — it never opens SSH itself and never receives passwords, keys, or host addresses.

| | |
|---|---|
| **For** | Ops / SRE / admins who use Cursor (or another MCP client) against real servers, but want secrets and connect decisions to stay human-side |
| **Not for** | Replacing Termius/mRemoteNG as a general-purpose remote manager, or unattended bot SSH into production |

## How it works

1. Unlock a local encrypted vault (hosts, addresses, credentials, scripts).
2. Open an SSH **Tab** yourself (or launch installed PuTTY / WinSCP).
3. Turn **MCP** on for that tab; once: toolbar **Copy MCP config** → paste into Cursor `mcp.json`.
4. The model uses `session_list` → `session_attach(alias=…)`, then read / subscribe. **Approve** (off by default) is required for write / script run.

Secrets and IPs stay out of MCP payloads. Approve off = read-only for the model.

## Download

Windows single-file build: [Releases](https://github.com/AtagyanAG/HostsKeeper/releases) (`HostsKeeper.exe`).  
SmartScreen may warn — the binary is unsigned. Optional: install PuTTY / WinSCP for external launchers.

## Development

Windows, Python ≥ 3.11:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python -m hostskeeper --version
pytest
python -m hostskeeper
```

Build exe: `.\scripts\build_exe.ps1` → `dist\HostsKeeper.exe` (see [doc/dev-setup.md](doc/dev-setup.md)).

Optional live SSH tests: set `HOSTSKEEPER_TEST_SSH_KEY` (and host/user if needed). Never commit vaults, keys, or `.env`.

## Docs

- [User guide](doc/user-guide.md) · [Requirements](doc/requirements.md) · [Architecture](doc/architecture.md)
- [MCP API](doc/mcp-api.md) · [Data model](doc/data-model.md) · [UI guidelines](doc/ui-guidelines.md)
- Full index: [doc/README.md](doc/README.md)

## License

[MIT](LICENSE). Third-party notices: [NOTICE](NOTICE).

HostsKeeper is **not affiliated with** PuTTY, WinSCP, or other products named in the UI or docs. Those tools are optional externals you install yourself; they are not redistributed here.
