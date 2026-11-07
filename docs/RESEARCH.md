# Compatibility research — 6 November 2026

## DynamicLake

Primary sources retrieved from the official DocC JSON at
`https://docs.dynamiclake.com/data/documentation/dynamiclakekit/<article>.json`.
The documentation site is JavaScript rendered; its public JSON was fetched over
HTTPS with certificate verification. No private APIs or binary inspection used.

- [JSON Plugin API](https://docs.dynamiclake.com/documentation/dynamiclakekit/jsonpluginapi)
- [Lakes and layout](https://docs.dynamiclake.com/documentation/dynamiclakekit/lakes)
- [Packaging and Market](https://docs.dynamiclake.com/documentation/dynamiclakekit/pluginpackagingandmarket)
- [Design guidelines](https://docs.dynamiclake.com/documentation/dynamiclakekit/designguidelines)
- [First plugin](https://docs.dynamiclake.com/documentation/dynamiclakekit/createyourfirstplugin)
- [Extension/SPM guidance](https://docs.dynamiclake.com/documentation/dynamiclakekit/addspm)
- [2.0 announcement](https://www.dynamiclake.com/blog/dynamiclake-2.0---dynamic-island-for-mac)
- [Plugins announcement](https://www.dynamiclake.com/blog/dynamiclake-market-and-plugins)

| Question | Established official contract |
| --- | --- |
| Architecture/languages | Local executable process; Python, Swift and other languages supported. Keep Python and standard library. |
| Protocol | `schemaVersion: 1`, 4-byte big-endian length, UTF-8 JSON over host-provided Unix socket. |
| Live surfaces | compactLiveActivity (two visual slots), extraLiveActivity (one glyph), sneakPeek (three slots). Descriptive text belongs in Sneak Peek. |
| Actions | Buttons return `actionID`, `activityID`, `surface`, optional `componentID` on the same socket; they do not execute commands. Host can disable callbacks. |
| Full Lake | Declare `lake` in manifest, send `lake` commands; user opens lake, plugin cannot force it open. `lakeOpened` identifies a pressed session activity. |
| Glance | Manifest `lake.glance` and separate compact command `glance` content; requires new host support. |
| Layout | `lakeLayout` enables stacks, scroll, spacers, bottom, custom Glance, native buttons and patches. Max depth 4, 160 components, 16 top-level; scroll at most 50 children. |
| SwiftUI | Arbitrary render code is not part of JSON. Legacy extensions provide SwiftUI; current extension guidance deprecates new extensions in favor of plugins. No companion app needed here. |
| Compatibility | Negotiate environment `DYNAMICLAKE_PLUGIN_FEATURES`; older hosts reject unknown fields. New manifest lake key may require a newer host at install time; reinstall 1.5.0 on old hosts if manifest rejected. |
| Images | SF Symbols preferred. `imageAssets` caches at most 16 images per connection, reregister after reconnect. |
| Size limits | ZIP 7 MB, extracted 20 MB, manifest 128 KB, square icon 1.5 MB, inline image 48 KB, asset 192 KB; JSON 64 KB or 256 KB with imageAssets. |
| Permissions | Supported macOS permissions are declared, requested and owned by DynamicLake. None needed here. Full Disk Access cannot be declared. Provider approvals are a different concept. |
| Files/background/network | Review notes must disclose them. Local processes/socket transport are the documented architecture. No blanket promise that arbitrary cross-app hooks will pass review. |
| Packaging | One `.dynamiclakeplugin` directory in ZIP, relative executable/icon paths, runnable executable. No mutable files in installed package. |
| Install/update/removal | Install Local copies/validates folder; retain identifier, increase version. Host verifies files and signed catalog hashes. Disable/remove plugin through host; remove optional provider hooks separately first. |
| Market | Submit at market.dynamiclake.com with developer/contact/category/summary/review notes; downloadable archive and matching hashes needed before live publication. Host-managed signed catalog approval is separate from local install. |
| Resource/remote asset rules | Documented payload/package limits above; no numerical CPU/battery/network budget or comprehensive asset license policy found. No remote assets or telemetry used. |

The public SDK repository at commit `987dd2888e90a450611dda022a381c2dad0cbfcc`
has an older binary interface without current Lake types. It is unsuitable as a
validator for the newer web documentation. The installed DynamicLake Pro reports
2.0 but rejected a direct test client with **Client is not trusted**. We did not
bypass trust checks, modify its installation or replace the user's active plugin.
Full Lake rendering therefore remains unverified in the installed host.

## Provider evidence and boundaries

- [Codex App Server](https://learn.chatgpt.com/docs/app-server): initialization,
  account/rateLimits/read and client-owned approval RPC. This plugin starts a
  short-lived server **only for opt-in quota reads**, not to control unrelated
  sessions. Live local account read returned two valid windows during development;
  no account values, credentials or identifiers were printed or persisted.
- [Codex source](https://github.com/openai/codex): local rollout compatibility
  parser remains best-effort, not an event subscription to every other client.
- [Claude hooks](https://code.claude.com/docs/en/hooks): lifecycle/tool hooks and
  PermissionRequest's `hookSpecificOutput.decision.behavior` support one-shot
  allow/deny. PermissionRequest has no tool_use_id: the waiting hook connection
  and random single-use ID bind each request. No decision returns to native flow;
  noninteractive providers can deny rather than prompt. Existing hooks/policies
  still apply. Beta.2 additionally supports the documented local statusLine quota source below;
  no hidden account endpoint is used.
- [OpenCode server](https://docs.opencode.ai/docs/server/): existing TUI server
  exposes events and permission endpoints; starting another server is not an
  attachment to an existing TUI. The current official `dev` source's
  [permission handler](https://github.com/anomalyco/opencode/blob/dev/packages/server/src/handlers/permission.ts)
  uses a newer response envelope/decision API than the documentation's legacy
  endpoint. This beta deliberately provides read-only multi-session SQLite
  compatibility, **not** a speculative permission POST or unverified SSE client.
  Official live server attachment/approval is outstanding work requiring a
  version-negotiated adapter and a live server fixture. No database writes.

Provider versions may drift. Missing or incompatible files isolate one adapter;
all other providers continue. No unsupported action is advertised as available.

## Release questions, not asserted requirements

Market maintainers must confirm acceptance of optional external provider hooks,
the per-user hook bridge and installed Python 3.10+ runtime dependency. Numerical
battery targets, accessibility acceptance, installed-host behavior on notch/pill
and light/dark appearance need live testing. See [the source license](../LICENSE.md)
for permitted use and [the release checklist](../RELEASING.md) for Market distribution.

## OpenCode Desktop schema correction (beta.2)

The installed macOS OpenCode 2.2.5 contains both legacy and new tables. Actual
read-only schema inspection confirmed session_v2, session_message (type/seq/data),
and session_part (ordinal/type/call_id/data). New messages place tool name/id/state
in assistant content and record turn outcome in idle messages. The old adapter
read only session/message/part and therefore missed the new desktop's sessions.
The fix reads both, with v2 rows authoritative for migrated IDs.

Current official source corroborates the shapes:
[SQLite schema](https://github.com/anomalyco/opencode/blob/dev/packages/core/src/session/sql.ts),
[message schema](https://github.com/anomalyco/opencode/blob/dev/packages/schema/src/session-message.ts),
[channel database selection](https://github.com/anomalyco/opencode/blob/dev/packages/cli/src/database-path.ts).
No transcript text, tool output, secrets or actual project names were printed.
The installed database was read successfully with v2 detection; no new agent job
was launched to manufacture live activity. Automated fixtures cover running tools,
independent sessions, mixed migrations, idle failures/interruptions and channel DBs.

## Claude quota source (beta.2)

The official [status line documentation](https://code.claude.com/docs/en/statusline)
provides `rate_limits.five_hour` and `rate_limits.seven_day`, each with
`used_percentage` and `resets_at`. These are subscription limits, distinct from
`context_window.used_percentage`. Fields depend on the account and can be absent
until a response arrives; expired windows are omitted by Claude. The explicit
local collector validates those fields, excludes prompts/context/costs and sends
only normalized quota data over current-user IPC. No existing custom statusLine
is overwritten. This is automated contract-tested; real Claude input still needs
acceptance in an eligible running session.

## OpenCode quota retrieval and setup (beta.3)

The official [Console Go page](https://opencode.ai/console/go) distinguishes daily
free-model request limits from Go’s five-hour/weekly/monthly allowances. The
[Go guide](https://opencode.ai/docs/console/go) explains model/tier-dependent
allowances. `opencode.allowance` in inference responses is a per-request debit,
not a remaining account snapshot, so the plugin does not sum local requests into
a fabricated account percentage.

The current public [usage API group](https://github.com/anomalyco/opencode/blob/dev/packages/protocol/src/groups/usage.ts)
exposes operation `experimental.usage.limits` and its
[UsageLimits schema](https://github.com/anomalyco/opencode/blob/dev/packages/schema/src/usage-limits.ts)
provides Go percentages and millisecond reset timestamps, plus Console budgets.
The [native CLI API handler](https://github.com/anomalyco/opencode/blob/dev/packages/cli/src/commands/handlers/api.ts)
resolves authentication through OpenCode itself. The installed 2.2.5 CLI’s public
help confirms `api` and `--standalone`; a live call returned a valid location/data
envelope with null data. No credentials or account values were printed. This
establishes the retrieval route, not a populated paid quota on this account.

DynamicLake’s documented manifest setting types remain switch/slider/select/button;
setting buttons accept only HTTP(S) URLs. Real setup callbacks therefore live in a
gear-initiated Lake flow, using the documented native button callback mechanism.
No custom executable setting type, private deep link or public setup server is added.
