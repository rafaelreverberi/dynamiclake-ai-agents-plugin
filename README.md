# AI Agents for DynamicLake

**Codex · Claude Code · OpenCode** — focused progress and usage in your Mac's notch.

Version **2.0.1** includes a Progress view with
agent image, current action and recent steps; a Usage view with three
logo-centered remaining-quota rings. The two circular switches sit at the top.
A gear button opens guided provider setup; there is no general diagnostics page. The original package icon and agent images
are preserved. The minimized activity always shows the selected active agent image.

Concurrent sessions are tracked independently; one stable session is selected for
the compact notch. Small arrows in Progress cycle between them. Actual completion,
error and permission symbols and notifications are retained. Unknown progress and
unknown account quotas are never turned into invented percentages.

## Install/update

Requires macOS, a recent DynamicLake Pro/Playground with JSON plugin support, and
Python 3.10+ available as `python3`. Identifier remains
`com.dynamiclake.plugins.ai-agents` for in-place updates.

1. Build with `PYTHONDONTWRITEBYTECODE=1 python3 scripts/build_release.py`, or download
   the ZIP and SHA-256 checksum from [GitHub Releases](https://github.com/rafaelreverberi/dynamiclake-ai-agents-plugin/releases/latest).
2. Verify using `shasum -a 256 -c AI-Agents-2.0.1.zip.sha256` in that directory.
3. Extract and select `AIAgents.dynamiclakeplugin` in DynamicLake's
   **Settings → Plugins → Install Local**. Confirm installation and enable it.
4. Use Smart Left Click on its activity, or assign AI Agents as the click Lake.

New layouts require advertised `lake` and `lakeLayout` features. Older hosts get a
minimal supported header; a host rejecting the manifest lake key needs updating.
Do not change installed package files: rebuild/reinstall through the host.

## OpenCode Desktop fix

The new desktop writes `session_v2`, `session_message` and `session_part`, while
retaining legacy tables. Reading only the old tables misses new sessions. This
build reads both schemas, extracts inline assistant tools, honors idle success /
failure / interruption and suppresses migrated duplicates. It also discovers
`opencode*.db` channel variants under `$XDG_DATA_HOME/opencode` or
`~/.local/share/opencode`. All database access is read-only. `OPENCODE_DB` remains
an explicit override. The installed 2.2.5 schema was checked without printing
private contents; lifecycle behavior is covered by synthetic regression fixtures.

## Usage and privacy

**Usage & limits** is on by default for new installations. Codex reads its account
quota through its own `codex app-server` login. Rings show **remaining**, with available
5-hour/weekly windows. Tap a ring for the quota source, remaining time, and reset time in your local time zone. OpenCode reads Go allowances and Console budgets through its own current CLI.
Free-model daily counters are not supplied by that API. Claude can receive its
authentic limits through the local collector below. No fake usage totals.
Account reads may contact OpenAI through Codex; no credentials are extracted.

File names are visible by default, matching the mockups; use Hide file names or
Hide project names for screen sharing. Existing saved privacy values are retained.
Task titles come from metadata, never inferred from a prompt. Original Codex/Claude
logo variant preferences remain available. The obsolete showAgentLogos setting no
longer hides identity images. Routine tool events do not trigger notifications.

## Guided setup and simpler settings

Open the **gear** in the Lake, then **Setup Claude**, **Setup Codex** or **Setup
OpenCode**. Claude setup shows what will change and applies it only after Connect;
it preserves custom displays and existing hooks. Codex approvals use an optional hook. OpenCode can
check its Console limits or open the official Console/limit guide. Native settings
include usage, OpenCode monitoring, optional Claude hooks and approvals, notifications,
privacy controls, image choices, and two opt-in display switches. **Hide setup button**
hides the gear. **Show Usage when idle** makes Usage the default Lake view
between tasks without creating a live activity. Use **Usage & limits** to control account quota reads.
Saved legacy options remain readable when supplied by the host.

[Setup guide and default settings](docs/SETUP.md)

Tab/window clicks now publish from cached state immediately instead of waiting
for the monitoring interval. Lake and Glance content have more side padding, with
an additional inset around the operation detail column.

## Optional Claude quota input

Claude Code's documented `statusLine` JSON can provide actual 5-hour/weekly limits
for eligible subscriptions, after its first API response. No auth token or extra
Claude network request is needed. To forward only those quota fields to the plugin:

```sh
python3 /absolute/path/AIAgents.dynamiclakeplugin/integrations.py install-usage claude
```

Enable **Account usage** in Plugin Settings. This explicitly configures a compact
Claude terminal status line and forwards quotas over the private local socket;
it is not another DynamicLake screen. If you already have a custom status line,
the installer refuses to replace it and leaves the configuration unchanged.
Remove only this collector with `uninstall-usage claude`; the normal `uninstall
claude` command also removes this plugin's own collector. Missing/expired windows
remain unavailable, never inferred from context-window percentages.

## Optional Claude hooks and approvals

Monitoring works without hooks. To use documented Claude lifecycle/permission hooks,
explicitly run the installer from the **installed** package location:

```sh
python3 /absolute/path/AIAgents.dynamiclakeplugin/integrations.py install claude
```

Then enable **Local provider hooks**, and optionally **Claude approval controls**.
The installer preserves unrelated hooks, backs up the original configuration
privately and avoids duplicates. Restart the Claude session to load changes.
Requests use a private per-user Unix socket, one-shot IDs and a 90-second timeout.
Timeout/disconnect/shutdown restores native permission handling, never implicit
approval. No permanent permission rules or tool inputs are rewritten. Oversized
inputs use the original agent prompt. A queued decision is not tool success.

Before removal:

```sh
python3 /absolute/path/AIAgents.dynamiclakeplugin/integrations.py uninstall claude
```

Disable/remove the plugin through DynamicLake. Optional provider backups remain
beside the original config and can contain its pre-existing private settings.
No event/transcript cache is written. No other providers have hook installers.

## OpenCode online usage

With Usage enabled, a bounded background worker invokes the current OpenCode CLI's
`api experimental.usage.limits --standalone`. It prefers the Desktop app's CLI,
uses OpenCode's own authentication, reads no credential stores and shuts down its
private CLI process. Requests are independent of Codex reads and do not block view
switches. The endpoint is experimental; old CLIs or absent Console/default-location
context can return no data. A live probe succeeded on the installed CLI but returned
`data: null`; paid Go values have not been live-confirmed on this account.

Go exposes actual 5-hour/weekly/monthly percentages. Console monthly budgets are
labeled separately; per-model budgets are not generalized into one account ring.
Free-model daily counts are not supplied by this contract and remain unknown.
No inference call is made to test limits, and no tiers/prices are guessed.

## Verification and limits

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
./AIAgents.dynamiclakeplugin/ai-agents-monitor.py --check
PYTHONDONTWRITEBYTECODE=1 python3 scripts/build_release.py
```

The builder validates/package-tests the extracted runtime, including concurrent
tracking, one compact activity, Usage callbacks, reconnect and clean shutdown.
`--check` prints counts only. `--demo-json` follows privacy settings and should be
used only where displaying local activity metadata is appropriate.

The user supplied real beta.2 screenshots confirming the native baseline layout.
The beta.3 setup/padding changes still need visual acceptance in the installed host. Automated payload checks are not proof of
native rendering or Market approval. No integration was installed into the user’s Claude configuration during development;
setup tests use temporary fixtures.

[Capabilities/UI](docs/CAPABILITIES.md) · [Architecture](docs/ARCHITECTURE.md) ·
[Research](docs/RESEARCH.md) · [Privacy](PRIVACY.md) · [Security](SECURITY.md) ·
[Assets](ASSETS.md) · [Release checklist](RELEASING.md)

Independent software by Rafael Reverberi; no affiliation with DynamicLake, OpenAI,
Anthropic or OpenCode. Existing source/asset terms remain unchanged.
