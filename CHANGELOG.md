# Changelog

This file records changes to the AI Agents DynamicLake plugin. The package version is defined in `AIAgents.dynamiclakeplugin/plugin.json`.

## 1.5.0 — 2026-09-20

### Added

- Codex and Claude logo dropdowns in Plugin Settings, with the existing ChatGPT/OpenAI and Claude marks retained as defaults.
- Transparent Codex cloud and Claude Code mascot variants from images supplied for this update.

### Changed

- Logo changes update active activities, including the minimized side capsule, without restarting the plugin.
- The bundled Codex and Claude Code marks keep their transparent backgrounds and shapes.

### Verification

- Unit tests cover both dropdown choices, invalid saved values, all logo surfaces, and updates to a running session.
- Package validation checks the dropdown definitions and all five bundled logo files.

## 1.4.0 — 2026-09-20

### Added

- OpenCode session monitoring through its local SQLite database, opened read only.
- An OpenCode on/off switch alongside DynamicLake's existing Codex and Claude controls. The plugin uses the host's built-in Codex and Claude values, avoiding duplicate switches.
- An optional setting to show agent logos in the main Live Activity and Sneak Peek.
- A minimized side capsule that always identifies the agent by its logo, even when the main-view logo setting is off.
- Bundled OpenAI, Claude, and OpenCode logo assets so display does not require a network request.

### Changed

- On completion with the logo setting enabled, the agent logo remains on the left and a green checkmark appears on the right. The minimized capsule continues to show the agent logo.
- Socket writes tolerate larger inline image payloads without partial nonblocking writes.
- Attribute the plugin to Rafael Reverberi in its manifest while retaining the existing identifier for upgrades.
- Reconcile existing Live Activities when the monitor starts, dismissing any activity whose source is off or whose session is no longer active.
- Use Codex activity events to time session expiry so later settings metadata writes do not make a completed session appear recent again.
- Keep Codex turn state within the file tail for large session logs; an old turn ID from the file header could otherwise cause the latest completion event to be ignored.

### Verification

- Unit tests cover OpenCode parsing, source switches, logo settings, completion layout, minimized layout, startup cleanup, Codex metadata writes, and large Codex logs.
- DynamicLake's JSON parser accepted sample messages for logo-enabled, logo-disabled, and completed states up to its installed-client trust check. The user confirmed the installed layout visually.

## 1.3.0 — previous package

- Monitored local Codex and Claude sessions and showed their activity status in DynamicLake.
- Supported environment configuration for source visibility and activity timeouts.
