# Set up AI Agents

## Open the setup menu

1. Open the full AI Agents view in DynamicLake.
2. Select the **gear** at the top of the view.
3. Choose **Setup Claude**, **Setup Codex**, or **Setup OpenCode**.
4. Check **Usage & limits** in the plugin settings if account limits are missing.

## Update optional integrations from 2.0.1 or earlier

The old hooks and Claude status line reference Python and scripts from the
previous package. After updating to 2.0.2, refresh only the integrations you
already use. The setup commands replace this plugin's entries in place and keep
other hooks and custom status lines. DynamicLake does not edit provider settings
on startup.

Replace the example path with the executable in the plugin folder managed by
DynamicLake, rather than a copy in Downloads:

```sh
ai_agents="/path/to/installed/plugin.dynamiclakeplugin/ai-agents"
"$ai_agents" --setup install claude        # Claude activity and approval hooks
"$ai_agents" --setup install-usage claude  # Claude usage collector
"$ai_agents" --setup install codex         # Codex approval hook
```

The same integrations can be removed and added again in the usual Setup screens.
If you used a custom status line to call the old script directly, update its
command as described below. Restart the affected provider sessions and trust
the changed Codex hook in Codex if prompted. No action is needed if you only use
normal activity tracking.

## Default settings

These defaults apply to a fresh installation. DynamicLake can keep your saved
choices when you update the plugin. Claude activity hooks receive events after
you install the hooks in Setup Claude. Approval decisions remain opt-in.

| Setting | Default |
| --- | --- |
| Show Usage when idle | Off |
| Usage & limits | On |
| Hide setup button | Off |
| OpenCode monitoring | On |
| Claude activity hooks | On |
| Claude approvals | Off |
| Codex approvals | Off |
| Notifications | On |
| Privacy · hide task names | Off |
| Privacy · hide file names | Off |
| Appearance · Codex image | Codex |
| Appearance · Claude image | Claude Code |

The plugin is configured to start automatically. DynamicLake manages the
separate Codex and Claude monitoring switches, which default to on if the host
does not supply a value.

**Hide setup button** controls whether the gear is visible. To show it again,
turn this setting off in DynamicLake's plugin settings. **Show Usage when idle**
makes Usage the default full view when you open AI Agents between tasks. You can
open AI Agents from DynaGlance or assign it as a click Lake in DynamicLake.

## Claude Code usage and approvals

Enabling **Usage & limits** starts the usage receiver. Claude Code also needs a
local status line that forwards its account limits.

1. Open **Setup Claude → Connect Claude usage**.
2. Review the proposed change and select **Connect**.
3. Open a Claude Code session. Eligible accounts report usage after the next response.

Setup adds a local status line and forwards the five-hour and weekly limits.
The plugin updates `~/.claude/settings.json`, or `settings.json` under
`CLAUDE_HOME` if set. It saves a private backup before replacing the file
atomically. Existing settings and hooks are preserved. Missing quota data appears
as **Unavailable**. [Claude Code status line documentation](https://code.claude.com/docs/en/statusline)

An existing custom status line stays in place. To keep it and also forward usage,
have your script pass the same JSON input to `ai-agents --hook claude Usage` in the
installed package. Use a subprocess timeout, discard the hook's output, and keep
your script's original output. The hook needs no credentials.

For approvals, open **Setup Claude → Install approval and activity hooks** and
confirm the preview. Restart Claude Code, then enable **Claude activity hooks**
and **Claude approvals** in the plugin settings. The local `PermissionRequest`
hook handles supported requests one at a time. [Claude Code hook documentation](https://code.claude.com/docs/en/hooks#permissionrequest)

## Codex usage and approvals

The plugin reads local session metadata for progress and uses the Codex app
server for account limits. Open **Setup Codex → Check usage**. If needed, sign
in through Codex first.

For approvals, select **Setup Codex → Install approval hook** and confirm the
preview. In Codex, review and trust the hook under **Settings → Hooks** or
through `/hooks` in the terminal. Then enable **Codex approvals** in the plugin
settings.

For either agent, **Notifications** shows new approval requests in the notch.
Open the preview, review the action in the Lake, and select **Approve once** or
**Deny**. Closing the Lake leaves the request pending.

## OpenCode usage

- **Free models** have daily request limits. The experimental usage API does not
  supply a general remaining daily count for free models. [OpenCode Console](https://opencode.ai/console/go)
- **Go, Go Plus, and Go Teams** have five-hour, weekly, and monthly windows.
  The service supplies the percentages for your plan and model. [OpenCode Go guide](https://opencode.ai/docs/console/go)
- **Console budgets** are spending limits. Global monthly budgets appear as a
  member or workspace budget.
- **External providers and personal API keys** use the respective provider's
  limits.

Open **Setup OpenCode → Open Console** or **Check usage**. Sign in to OpenCode
Console and select the relevant workspace in OpenCode. The plugin uses the CLI
from the installed macOS app when available and otherwise uses `opencode` from
`PATH`. It runs this usage query through a private CLI server:

```sh
opencode api experimental.usage.limits --standalone
```

The CLI handles authentication. The plugin leaves the existing background
service and running jobs alone. While usage tracking is enabled, it checks
automatically at most once every five minutes. Disabling usage tracking cancels
in-flight checks.

An older CLI, a missing Console context, or a response containing
`"data": null` can cause **Unavailable**. The CLI's default context can differ
from a project's Console context. In that case, check the account in OpenCode
Console directly.

Handle approval requests in OpenCode. If you configured the experimental
integration from an earlier beta, you can remove the `opencode-approvals`
entry from your OpenCode configuration.

## Remove integrations

In **Setup Claude**, select **Remove usage input** or
**Remove approval and activity hooks**, then confirm the preview. Removing the
hooks leaves the usage input installed. You can also use the CLI:

```sh
"/path/to/installed/package/ai-agents" --setup uninstall-usage claude
"/path/to/installed/package/ai-agents" --setup uninstall claude
```

The second command removes this plugin's marked Claude entries, including the
usage input. To remove the Codex integration, select **Remove approval hook**
in **Setup Codex** and confirm the preview. Private backups remain next to the
original configuration. You can then disable or remove the plugin in DynamicLake.
