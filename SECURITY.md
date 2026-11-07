# Security

Report sensitive issues privately to the
repository owner. Use synthetic reproduction data; do not paste transcripts,
credentials, tokens, account identifiers, permission inputs or private paths.

The default runtime is read-only local monitoring. Optional decisions use the
documented Codex and Claude PermissionRequest hooks.
A 0700 current-user directory and 0600 Unix socket isolate the hook bridge from
other users. Messages are bounded, normalized and queued in memory. Pending
requests have random single-use IDs, original waiting connections, expiration,
connection-liveness checks and a bounded decision queue. Oversized/incomplete
previews cannot be approved. Native policies and other hooks are preserved.

Socket loss/shutdown cancels pending review; provider-native flow resumes. A sent
decision is not reported as tool success. Allow and Deny require the selected request on the open Lake review page.
Mismatched and replayed callbacks fail.
Same-user software can access this user's resources and is not an isolation
boundary. Host-provided callback permissions and trusted plugin installation still
apply; this project does not bypass them.

Quota reads use the Codex CLI's supported account interface with a bounded worker;
no credentials are extracted. Codex and Claude setup uses locked atomic updates,
private backups and marker-based uninstall.
No provider config is changed by starting the monitor. Package builds exclude
personal settings, transcripts, caches . Runtime disables
bytecode writes because DynamicLake verifies installed package contents.

See [PRIVACY.md](PRIVACY.md) and [docs/RESEARCH.md](docs/RESEARCH.md) for access
boundaries, source evidence and remaining live acceptance checks.
