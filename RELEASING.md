# Release review — 2.0.2

GitHub Releases distributes the ZIP for local installation in DynamicLake.
DynamicLake Market has its own submission and review process.

## Reproduce

Build on macOS with Xcode or its command line tools, Python 3.10+ with pip,
and network access. On Apple Silicon, install Rosetta on the build machine to
verify the Intel slice. These are build and test requirements only.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/build_release.py
cd dist
shasum -a 256 -c AI-Agents-2.0.2.zip.sha256
```

The builder checks the CPython source checksum and uses pinned, hash-verified
PyInstaller wheels. It builds universal2 runtime files against Apple system
libraries, then checks both slices, code signatures, load paths and deployment
targets. One executable runs the monitor, optional setup commands and all
Python-based provider hooks. PyInstaller's directory mode keeps the runtime in
the plugin folder, so a hook can start it directly without unpacking a temporary
copy. CPython and PyInstaller notices are included under `licenses/`.

Unit tests and a smoke test gate the ZIP. The smoke test extracts it through
macOS, runs it with no Python on PATH and covers old hook upgrades, hook protocol
and fallback, OpenCode SQLite, branding assets, concurrent activities, callbacks,
privacy, reconnect and graceful shutdown. ZIP members have fixed timestamps and
sorted names. Compiler, SDK and compression versions can change the bytes.
The local binaries use ad-hoc signatures; the DynamicLake catalog signature
and publication are handled by the Market.

For future updates, review CPython and PyInstaller security and maintenance
releases, update the versions and hashes in the build scripts, and rerun the
full build on both architectures.

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

1. Confirm Market distribution permissions with the repository owner. The source
   terms are in [LICENSE.md](LICENSE.md), and artwork provenance is in [ASSETS.md](ASSETS.md).
2. Obtain the above host/provider acceptance evidence and review documented limits.
3. Disclose local metadata reads, optional provider configuration changes/backups,
   current-user hook IPC, background polling, bundled Python runtime and optional
   Codex/OpenAI account requests in submission notes.
4. Ask maintainers to confirm these optional cross-app hooks and bundled runtime
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
