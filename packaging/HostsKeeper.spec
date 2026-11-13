# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec: single-file HostsKeeper.exe (Windows + PySide6 + MCP HTTP).
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve().parent
SRC = ROOT / "src"

# Do NOT collect_all('PySide6') — pulls WebEngine/Qt3D (~200MB+). Hooks from
# QtWidgets/QtGui/QtCore imports are enough for HostsKeeper desktop.

hiddenimports: list = [
    "uvicorn.logging",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan.on",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "anyio._backends._asyncio",
    "starlette.routing",
    "starlette.middleware",
    "starlette.middleware.base",
    "mcp.server.streamable_http",
    "mcp.server.streamable_http_manager",
    "mcp.server.transport_security",
    "mcp.server.mcpserver",
    "mcp.server.lowlevel.server",
    "mcp.server.sse",
    "pyte",
    "markdown",
    "markdown.extensions.fenced_code",
    "markdown.extensions.tables",
    "markdown.extensions.nl2br",
    "markdown.extensions.sane_lists",
    "paramiko",
    "cryptography",
    "hostskeeper",
    "hostskeeper.desktop",
    "hostskeeper.desktop.app",
    "hostskeeper.desktop.main_window",
    "hostskeeper.desktop.terminal_widget",
    "hostskeeper.mcp.http_app",
    "hostskeeper.mcp.server",
    "hostskeeper.runtime.mcp_http",
]

try:
    hiddenimports += collect_submodules(
        "mcp",
        filter=lambda name: not name.startswith("mcp.cli"),
        on_error="ignore",
    )
except Exception:
    pass

for pkg in ("uvicorn", "starlette"):
    try:
        hiddenimports += collect_submodules(pkg, on_error="ignore")
    except Exception:
        pass

a = Analysis(
    [str(SRC / "hostskeeper" / "__main__.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=[],
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "numpy",
        "pandas",
        "IPython",
        "notebook",
        "mcp.cli",
        "PySide6.QtWebEngine",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineQuick",
        "PySide6.Qt3DCore",
        "PySide6.Qt3DRender",
        "PySide6.Qt3DInput",
        "PySide6.Qt3DLogic",
        "PySide6.Qt3DAnimation",
        "PySide6.Qt3DExtras",
        "PySide6.QtQuick",
        "PySide6.QtQuickWidgets",
        "PySide6.QtQml",
        "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets",
        "PySide6.QtPdf",
        "PySide6.QtPdfWidgets",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtBluetooth",
        "PySide6.QtNfc",
        "PySide6.QtPositioning",
        "PySide6.QtLocation",
        "PySide6.QtSensors",
        "PySide6.QtSerialPort",
        "PySide6.QtWebSockets",
        "PySide6.QtWebChannel",
        "PySide6.QtWebView",
        "pytest",
        "anyio.pytest_plugin",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="HostsKeeper",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
