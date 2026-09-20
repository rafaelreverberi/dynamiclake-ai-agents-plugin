# Security

Version 1.4.0 is the currently supported private release.

Report security issues through a private issue in this repository. Describe the behavior and reproduction steps, but do not include raw Codex, Claude, or OpenCode session files, prompts, credentials, tokens, or full project paths. If a minimal sample is needed, use synthetic data.

The plugin reads local session metadata and sends activity updates only to DynamicLake's local JSON plugin socket. It does not require an API key or send agent content to a remote service.
