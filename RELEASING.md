# Release review — 2.0.0

GitHub Releases distributes the ZIP for local installation in DynamicLake.
DynamicLake Market has its own submission and review process.

## Reproduce

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/build_release.py
cd dist
shasum -a 256 -c AI-Agents-2.0.0.zip.sha256
```

The builder runs unit tests, validates Python syntax, identity/version/settings,
executable bits, bundled agent images, icon/package/payload limits, ZIP integrity and
an isolated extracted-package check. A synthetic host starts the actual extracted
monitor and verifies concurrent activities, a Full Lake callback, privacy and clean
shutdown. ZIP members have fixed timestamps/modes and sorted order; rebuilding the
same bytes on the same compression runtime produces the same SHA-256. Python/zlib
version differences can affect compression bytes.

## Additional checks for Market submission

- Install this exact archive through DynamicLake's **Install Local** flow, leaving
  host trust protections intact. Direct socket clients are rejected as untrusted.
- Verify the advertised feature environment, manifest, all views/callbacks, older
  feature fallbacks, reconnect and disable/remove behavior in the trusted host.
- Check notch and pill, dark/light, keyboard/VoiceOver and callback-disabled mode.
- Verify real concurrent Codex/Claude/OpenCode sessions and new OpenCode Desktop v2 storage.
- Explicitly install Claude hooks, preserve existing hooks and test real allow,
  deny, native policy interaction, expiry/cancellation and restart cleanup.
- Confirm monitoring battery/CPU on a large real session tree and long tasks.
- Repeat Codex quota with offline, unsupported-account and authentication
  expiry behavior. Development's successful read establishes only that account
  request, not future account/provider compatibility.

## Market submission blockers

1. Resolve source distribution/license terms with the repository owner; no license
   has been silently assigned. Existing agent artwork has been restored as requested; provenance remains in ASSETS.md.
2. Obtain the above host/provider acceptance evidence and review documented limits.
3. Disclose local metadata reads, optional provider configuration changes/backups,
   current-user hook IPC, background polling, installed Python dependency and optional
   Codex/OpenAI account requests in submission notes.
4. Ask maintainers to confirm these optional cross-app hooks/runtime dependencies
   are acceptable. Official docs don't guarantee approval of this particular plugin.
5. Provide support/contact, release notes, downloadable package URL, archive hash
   and **host-compatible extracted package hash**. Its exact canonical hashing
   algorithm/signing flow is managed by DynamicLake; do not invent it.
6. Submit at https://market.dynamiclake.com. Signed catalog publication and review
   status are managed by DynamicLake. No submission or publication was performed.

For GitHub releases, retain the identifier and increase the version. Tag the
tested source, attach the installable ZIP and checksum, and verify the CI run.

Beta.3 adds a confirmed, reversible Claude setup flow and a read-only OpenCode
quota operation delegated to the native CLI. Disclose that OpenCode may contact
Console services and manages its own normal authentication/runtime caches. Direct
SQLite monitoring remains read-only. Native beta.2 rendering is user-confirmed by
screenshots; beta.3 padding/setup and populated Go allowances remain live checks.
