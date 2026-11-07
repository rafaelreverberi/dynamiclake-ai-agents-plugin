# Executed validation — 6 November 2026

- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -q`:
  **87 tests passed**, including all 12 retained/adapted regression cases.
- The packaged `agent_hook.py` stdin/stdout contract is tested through a real
  subprocess and private Unix socket: a decision returns documented Claude JSON.
  The original provider process is synthetic, not an actual Claude permission prompt.
- `./AIAgents.dynamiclakeplugin/ai-agents-monitor.py --check`: succeeded against
  available local metadata, printing provider counts only.
- `read_codex_quota()` against the installed Codex CLI: **2 actual validated quota
  windows returned**. No values/credentials/account identifiers printed or stored.
- A direct framed JSON probe of the installed DynamicLake Pro 2.0 returned
  `ok: false`, `Client is not trusted.` No trust protection was bypassed and no
  installed plugin/hook configuration was replaced.
- `python3 scripts/build_release.py`: validates manifest/version/size limits,
  compiles every bundled Python module, runs the unit suite, verifies ZIP integrity
  and executable mode, checks an extracted package with isolated provider roots,
  then launches the extracted monitor against a synthetic framed socket host.
  That smoke test checks two concurrently tracked sessions, one selected compact activity, a Usage callback
  and three logo-centered rings, privacy, reconnect restoration and graceful SIGTERM shutdown without package mutation.

Coverage includes missing/incompatible provider data, corrupt and split JSONL,
rotation/truncation, bounded large logs, independent sessions/expiry, known/unknown
tool results, OpenCode v2 idle outcomes, used/remaining/freshness quota semantics, failed IPC,
permission expiry/deny/allow/replay/mismatched session/cancellation/restart,
settings reload, preserved hooks/uninstall, feature gates, UI component budgets
and framed socket fragmentation/length bounds. A successful synthetic host test
is not proof of native visual rendering or real provider acceptance.

## Not established

Trusted DynamicLake installation and visual acceptance; real Claude hooks and statusLine quota input;
actual multi-agent outage/restart/liveness behavior; VoiceOver and keyboard checks;
notch/pill/light/dark UI; production battery/CPU measurements; Market review;
public source distribution terms. OpenCode event-stream and permission control,
ownership of unrelated Codex sessions are not implemented.

## beta.2 regression additions

The latest suite includes new OpenCode Desktop-only and mixed-migration schemas,
inline tool state, separate session_part records, old-session/new-message activity,
idle outcomes, channel database discovery and non-revival by metadata changes.
A read-only probe recognized the actual installed OpenCode 2.2.5 v2 tables.

UI tests require agent images even when old showAgentLogos is false, exactly three
remaining-quota tiles, no diagnostics navigation, component budgets and selective
ring asset refresh. Claude quota tests exercise official rate-limit fields versus
context utilization, missing/invalid/expired values, explicit non-destructive setup,
subprocess IPC, disabled collection and prevention of fake activity sessions.

No installed host or provider configuration was changed. Native rendering, actual
Claude quota/permission input and real running OpenCode jobs remain acceptance
checks rather than conclusions inferred from synthetic fixtures.

## beta.3 validation additions

Tests cover same-call cached view publication without provider polling, inner
padding, reduced native settings, setup preview/cancel/expiry/single-use confirm,
custom-display preservation and independent hook/usage removal. OpenCode quota
fixtures cover Go windows, epoch conversion, missing/free data, global versus
model-specific budgets, a real fixture CLI subprocess with fixed read-only argv,
independent workers and late-result discard when usage is disabled.

A separate installed-CLI probe called the native experimental.usage.limits
operation in standalone mode and received location/data with null data. No model
request was sent and no populated Go quota is claimed. The packaged smoke test
also requires a view response within 0.8 seconds, independent of the poll cycle.
User screenshots verify native beta.2 baseline rendering, not beta.3 placement or
setup acceptance. No setup was applied to the user’s real Claude configuration.
