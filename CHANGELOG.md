# Changelog

This file records changes to the AI Agents DynamicLake plugin. The package version is defined in `AIAgents.dynamiclakeplugin/plugin.json`.

## 2.0.1 — 2026-11-07

- Format long quota windows and reset countdowns in days, hours, and minutes.
- Show quota reset and last-check times in the Mac's local time zone.

## 2.0.0 — 2026-11-07

- Publish AI Agents 2.0 with Progress, Usage, DynaGlance, and optional Claude and Codex approvals.
- Enable usage tracking, OpenCode monitoring, Claude activity hooks, and notifications on fresh installs.
- Put **Show Usage when idle** first in Settings and keep it off by default.
- Document setup and all default settings in English.

## 2.0.0-beta.9 — 2026-11-07

- Show a longer automatic approval preview and put both decision buttons in the Lake review.
- Use the Codex or Claude logo in the review header.

## 2.0.0-beta.8 — 2026-11-07

- Restore the detailed Progress view and show three compact usage rings in idle Components.

## 2.0.0-beta.7 — 2026-11-07

- Make Claude Code approval setup explicit and place its install action first.
- Retire the manual OpenCode approval integration and keep existing registrations loadable.
- Simplify Progress and Glance to the agent, current action and a short edit summary.

## 2.0.0-beta.6 — 2026-11-07

- Fix a blank Lake and Glance during active sessions by using a valid status icon size.
- Validate Lake icon sizes and nesting in the packaged runtime check.

## 2.0.0-beta.5 — 2026-11-07

- Keep the Usage Lake available between tasks without publishing an idle activity or Sneak Peek.
- Show the selected agent, current action, available quota and task count together in the left column.
- Add optional Codex and OpenCode approval integrations alongside Claude. Deny from the notification or open the Lake to review and decide.

## 2.0.0-beta.4 — 2026-11-07

- Add opt-in settings to hide the setup gear and keep AI Usage in the notch between tasks.
- Show remaining account usage alongside the running-task summary in always-on mode.
- Read structured Codex command events for file reads, searches and command outcomes. Show Thinking during reasoning.

## 2.0.0-beta.3 — 2026-11-06

- Reduce native settings to nine core rows and add guided provider setup behind a
  gear button. Claude changes require an explicit preview/confirmation and preserve
  custom displays; Codex clearly needs no hooks. Include a German setup guide.
- Publish view/window actions immediately from cached state instead of waiting
  for the next provider poll. Use socket waits rather than fixed callback sleeps.
- Inset all Lake content and the operation detail column; retain images and the
  existing Progress/Usage layout. Improve known shell tool labels.
- Read authentic OpenCode Go windows and Console budgets via its current CLI's
  experimental.usage.limits operation, using its own sign-in and a private bounded
  standalone server. Keep free-model daily counters unknown when not supplied.
- Isolate Codex/OpenCode quota workers, preserve cancellation and late-result
  protection, and show Monthly only when an actual monthly window exists.

## 2.0.0-beta.2 — 2026-11-06

- Restrict support to Codex, Claude Code and OpenCode; remove other-provider hooks,
  switches and UI. Retain the original package icon and actual agent images.
- Replace dashboard/status pages with focused Progress and Usage views matching
  the latest mockups: top circular switches, a short operation checklist and a
  secondary detail column; three remaining-quota rings with agent images inside.
- Always show the active agent image in the minimized activity. Track concurrent
  sessions but publish one stable selected session, with in-place session cycling.
- Repair the new OpenCode Desktop storage: session_v2/session_message/session_part,
  inline tool events, authoritative idle outcomes, channel databases and migrated
  row deduplication. Legacy Desktop storage remains supported read-only.
- Keep completion/error/approval status icons and configurable notifications.
- Quota rings show actual remaining account data; unknown quotas stay unavailable.
- Add an explicitly installed Claude quota collector using documented statusLine
  rate_limits; preserve existing custom status lines, and never confuse context
  utilization with account quota. No extra Claude authentication or network API.

## 2.0.0-beta.1 — 2026-11-06

- Add provider-neutral session, tool, permission and usage models; incremental
  JSONL readers and concurrent read-only OpenCode sessions with stable identities.
- Add feature-gated native Full Lake overview, session timeline, usage, diagnostics,
  paginated sessions and compact Glance. Keep collapsed activities `small`.
- Add explicit reversible Claude/Cursor hook installer, private bounded IPC and
  single-use Claude PermissionRequest decisions. Cursor hooks monitor only.
- Add opt-in genuine Codex account quota through its official app-server API;
  other quotas remain unavailable. A live read returned two validated windows.
- Add live privacy controls, notification toggles, native prompt fallback,
  reconnect/backoff, bounded framing and clean SIGTERM handling.
- Replace marks/undocumented icon with original geometric artwork and preserve
  old preference values. Runtime never writes bytecode into the installed package.
- Build deterministic archives with privacy/security/capability documentation,
  SHA-256, unit regressions and extracted-package framed-socket smoke testing.
- This is a beta: native rendering/provider approval acceptance and Market review
  remain outstanding. OpenCode SSE/approval and unrelated Codex/Cursor approval
  control are not implemented; no official approval or source license is claimed.

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
