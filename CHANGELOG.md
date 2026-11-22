# Changelog

## [0.1.2] - 2026-11-22

### Added

- Per-host MCP access control and filtering of host groups to include only groups containing accessible hosts.
- MCP execution for saved scripts with isolated output, run status and cancellation support.
- MCP-visible notes and improved script-run feedback in the desktop UI.

### Changed

- Improved MCP client setup and tool descriptions.
- Refined host, script, and group management, including nested groups and UI presentation.
- Synchronized external vault edits and persisted per-entity Markdown preview state.

### Fixed

- Fixed a reconnect failure dialog that could crash when shown from a worker thread.
- Improved script-run diagnostics and session output handling.
