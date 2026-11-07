# AI Agents 2.0 implementation plan

1. Retain Python 3.10+ and schema 1 framed Unix socket transport. Use official
   `lake`, `lakeLayout`, `imageAssets` and `presentSneakPeek` feature negotiation.
2. Preserve legacy parsers for compatibility, add bounded incremental readers,
   independent provider adapters, stable session identities and normalized task,
   permission and quota models. Isolate failures and reconnect cleanly.
3. Add opt-in Claude hooks with a current-user Unix socket bridge.
   Claude PermissionRequest can return a one-shot allow/deny; Other providers have no hook installer. Do not attach a second Codex server to
   control somebody else's session. Keep OpenCode SQLite read-only.
4. Build native Full Lake Progress/Usage views and a smaller
   Glance. Use real tool timelines and indeterminate progress when unknown.
5. Read Codex quota through its documented app-server method only on explicit
   usage opt-in, bounded/cached. Unknown quotas remain unavailable.
6. Test multi-session parsing, lifecycle, framing, privacy, approval routing and
   packaged execution; create deterministic ZIP/checksum. Market submission is
   blocked on live host/provider acceptance and unresolved asset rights.

All ten supplied mockups were inspected in the chat. Preserve their hierarchy
(identity, status, recent steps, detail, clear approval choices), with the host
owning glass/background/geometry. The Codex GitHub logo and OpenCode cloud in the
mockups are not authoritative branding. Use SF Symbols by default until existing
asset redistribution rights are established; retain bundled variants as opt-in.

## Regression test adaptation

The original 12 regression cases are retained. The source switch, active logo
update and startup cleanup cases now instantiate the modular Controller and use
synthetic adapter results, replacing their obsolete single-session loader mock.
Assertions use hashed per-session activity IDs for the three supported providers.
Legacy parser/payload helpers remain import-compatible; the production entry
point and `AgentsJSONPlugin()` both use the new Controller.

## beta.2 feedback implementation

Only Codex, Claude Code and OpenCode remain. Progress is a single focused task
with agent image, a three-step timeline and secondary operation details. Usage
places the three retained logos inside data-backed remaining-quota rings. The
header has the two circular view switches from the user's three new mockups.
No status/diagnostics screen or bottom tab bar. One session is selected for the
collapsed notch; all sessions remain tracked and can be cycled within Progress.

OpenCode Desktop 2.2.5 was inspected read-only. Its legacy session/message/part
tables coexist with session_v2/session_message/session_part. Only reading the
legacy tables misses new sessions. The adapter now recognizes both schemas,
extracts inline assistant tool content, uses authoritative idle outcomes, excludes
migrated legacy duplicates and discovers channel database files.
