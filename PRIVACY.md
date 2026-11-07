# Privacy — 2.0

Activity monitoring reads local Codex and Claude session metadata and OpenCode
SQLite in read-only mode. It sends normalized status to DynamicLake's
user-local socket. Optional approval integrations require explicit installation. No telemetry,
analytics, remote assets, transcript database, persistent event history or log file.
No Full Disk Access, Accessibility, screen automation or account-cookie scraping.

Project basenames appear by default and can be hidden. File names are visible by
default in beta.2, as requested by the user, and can be hidden; tool descriptions and recent steps are configurable. Full paths, prompts,
responses, environment variables, terminal output and tokens/credentials are not
included in normal UI payloads. Session IDs are hashed for activity identities;
normalized session metadata is kept in memory. Session parsers necessarily read
bounded local JSONL/SQLite content to extract state, then discard raw records.
Hook clients strip prompt/output/email/transcript fields before local IPC.

**Explicit exceptions:** opting into interactive review exposes the entire
bounded permission request, including command arguments or paths, to the local DynamicLake
approval detail, even with file names hidden. Review can contain secrets supplied
in a command; it is never logged, persisted or sent to a remote review service.
Disable the corresponding approval switch to keep review in the agent. Project privacy still
applies to approval headers. Exact input is not executed or rewritten by this plugin.

**Usage & limits** is on by default for new installations. It launches Codex's
account/rateLimits/read using Codex's own login. Codex may contact OpenAI. The plugin reads no auth files/tokens directly
and stores only quota windows/source/freshness in memory. Disable to clear in-memory
quota display. One bounded in-flight read may finish after disabling; its result
is discarded. Claude quotas are optional local input from its documented statusLine contract;
only session ID and validated rate-limit fields enter IPC. No prompt, cost, context
percentage or output is forwarded. The explicit installer preserves an existing
custom status line by refusing replacement. OpenCode usage is read through its own CLI and authenticated Console operation,
without opening auth stores. It may contact OpenCode services and manage its own
normal caches/credential refresh. The private standalone CLI server is bounded
and cleaned up; the user’s managed background service is not reconfigured.

Opt-in hook installation writes provider configuration and private exact backups;
those backups can include the user's pre-existing sensitive configuration. They
are local 0600 files and are not packaged or uploaded. Uninstall removes only this
plugin's marked hooks. Hook runtime files live in a private per-user directory;
no mutable runtime files are written inside the installed plugin package.

Removing the plugin requires removing its optional provider hooks separately.
There is no event cache to clear. Same-user malicious processes remain outside the
IPC trust boundary: a plugin cannot protect itself from all software acting as the
same macOS user. Avoid public screenshots of private permission details.

The gear-button setup changes Claude or Codex configuration only after showing a preview
and receiving an explicit Connect/Remove action. Setup introspection publishes
only whether this plugin’s entries or a custom display exist, never configuration
contents. Development tests use temporary configurations. Free-model usage is not
estimated, and per-model budgets are not exposed as generic account percentages.
