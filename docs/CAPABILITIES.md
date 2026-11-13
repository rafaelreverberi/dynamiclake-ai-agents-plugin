# Current capabilities — 2.0.2

Only **Codex, Claude Code and OpenCode** are supported. The interface has two
primary views, Progress and Usage. Permission review appears only for an actual
pending supported request. A gear opens user-requested provider setup; there is no general diagnostics screen.

| Capability | Codex | Claude Code | OpenCode |
| --- | --- | --- | --- |
| Concurrent monitoring | Incremental JSONL | Incremental JSONL / optional hooks | Legacy and new Desktop v2 SQLite |
| Tool activity | Calls/results | Tool IDs/results | Old part records, new inline content / session_part |
| Completion | Explicit turn events | end_turn / Stop | Legacy finish/error and v2 idle outcome |
| Interactive approval | Opt-in PermissionRequest hook | Opt-in PermissionRequest hook | In OpenCode |
| Account quota | Official account/rateLimits/read; live read previously succeeded | Official statusLine rate_limits, explicit local collector | Native CLI experimental.usage.limits; Go windows and global monthly budgets |

All providers have automated monitoring fixtures. Claude quota collection also has
a real subprocess/private-socket fixture and non-destructive installer tests. A read-only probe detected the
installed OpenCode Desktop 2.2.5 v2 schema alongside legacy storage. Native DynamicLake rendering and real Codex and Claude approval prompts still need a trusted installed host.

## Views

**Progress** shows the selected agent, its task and current action alongside recent
steps. **Components** shows a compact triangle of agent logos and remaining usage
when no task is active.

**Usage** presents three horizontal rings with actual agent images in their
centers, provider names and authentic `% left` values. Ring arc length means
remaining quota, not used quota. A faint empty track plus Unavailable means no
supported quota data, not zero usage. Available Codex/Claude 5-hour/weekly windows can be
switched; tap a ring for its source, freshness and reset. Stale values are marked.
Quota monitoring remains configurable. Codex uses its own authorized CLI login;
Claude supplies documented local rate-limit fields without plugin credential access.

**Collapsed and side capsule** always contain the selected agent image, regardless
of the obsolete saved showAgentLogos value. Only one session is published to avoid
a cluster of competing activities. All sessions remain tracked; use the small
previous/next controls in Progress to change selection. Approval/error attention
has priority; the ordinary selection stays stable. With no work, no idle activity
is published. Completion/error/permission indicators and notifications remain.

**Glance/Sneak Peek** keep the same agent identity and concise operation summary.
The host owns background/glass, corners, adaptive sizing, text and native controls.
Unsupported arbitrary card backgrounds are not invented in the JSON payload.

## Runtime and privacy

File names are shown by default for the requested task view and can be hidden;
existing saved privacy choices remain authoritative. Project/task names can be
hidden. No prompts, responses, credentials or terminal output appear in normal UI.
Optional permission review shows the bounded exact tool input locally.

Per file provider: at most 64 recent sessions, eight retained steps, bounded head /
tail reads and incremental append processing. OpenCode supports up to eight local
channel databases, read-only connections closed after use, WAL-aware cache keys,
a query deadline, 64 sessions and twelve recent messages per session. Migration
rows are suppressed when the same ID exists in v2. Session/metadata edits cannot
revive old completed work. Discovery is ten seconds; polling one second active /
three seconds idle. Sparse long-running work can age out; freshness is adjustable.
Hook queues and pending decisions remain bounded, transient and current-user-only.

OpenCode Desktop channel databases matching `opencode*.db` are discovered under
`$XDG_DATA_HOME/opencode` or `~/.local/share/opencode`. Set `OPENCODE_DB` to
override discovery with a specific database.

No provider hooks/configuration or installed DynamicLake plugin were changed by
this development work. Source/asset distribution terms and Market acceptance are
not inferred from automated tests. See RESEARCH.md and RELEASING.md for evidence.

## beta.3 feedback changes

Immediate cached-state publication handles navigation/window clicks independently
of provider polling. Lake content has 16-point extra side insets and operation
details an additional 12 points; Glance uses eight. Setup has provider cards, a
review step for Claude edits, connection checks and source/help links. Native
settings have nine core rows and one notification toggle; legacy option values
remain readable. Codex never advertises fictitious hook setup.

OpenCode usage delegates to its own current CLI and experimental API, with an
independent bounded worker. Go windows are percentages already normalized by
OpenCode; monthly Console budgets are labeled as budgets. Free daily counters and
per-model budgets are not turned into one invented quota. The live CLI probe
returned a valid envelope with null data, so populated Go windows remain fixture-
tested rather than live-confirmed. Provider/Console context and an eligible account
are necessary; see SETUP.md for precise setup and limitations.
