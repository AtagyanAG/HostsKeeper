# HostsKeeper

<p align="center">
  <img src="src/hostskeeper/resources/hostskeeper.png" alt="HostsKeeper" width="128" height="128">
</p>

**Local credential vault + human-gated SSH tabs for MCP/AI — not a generic remote desktop.**

HostsKeeper keeps host credentials and shell scripts on your Windows PC. **You** open SSH sessions in tabs. An AI client (e.g. Cursor) attaches only to tabs you enable for MCP — it never opens SSH itself and never receives passwords, keys, or host addresses.

| | |
|---|---|
| **For** | Ops / SRE / admins who use Cursor (or another MCP client) against real servers, but want secrets and connect decisions to stay human-side |
| **Not for** | Replacing Termius/mRemoteNG as a general-purpose remote manager, or unattended bot SSH into production |

## How it works

1. Unlock a local encrypted vault (hosts, addresses, credentials, scripts).
2. Open an SSH **Tab** yourself (or launch installed PuTTY / WinSCP). Optional **port knocking** (TCP/UDP sequence) can run on an Address before connect.
3. Turn **MCP** on for that tab; once: toolbar **Copy MCP config** → paste into Cursor `mcp.json`.
4. The model uses `session_list` → `session_attach(alias=…)`, then read / subscribe. **Approve** (off by default) is required for write / script run.

Secrets and IPs stay out of MCP payloads. Human and AI share **one PTY per tab**:

- **Approve off (default):** the model may still **read** / subscribe to the terminal scrollback; it cannot `session_write` or `scripts_run`.
- **Approve on:** the model may write; every command it sends appears in the **same tab you see** — there is no hidden side channel.

## MCP over HTTP (not just local stdio)

HostsKeeper exposes MCP primarily as an **HTTP** endpoint with a stable **app key** (toolbar **Copy MCP config** → `http://<safe-host>:8765/mcp?key=…`). That is wider than a typical stdio MCP server glued to one local IDE process:

- The AI client can run on the **same PC** (`127.0.0.1`) or on **another machine** that can reach the vault PC.
- Credentials and SSH stay on the safe host; the client only sees enabled tabs (and scripts) under your MCP rules.

**Trusted network only.** Intended for LAN or a **VPN / tunnel you operate yourself** (VPN setup is out of scope for this project). Do not expose the MCP port to the open internet without such a tunnel. **stdio** remains available as a same-machine alternative (no URL/key).

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
