# Asset provenance

The three bundled agent marks identify the monitored products. They remain the property of their respective owners; their inclusion does not imply affiliation or endorsement. The plugin loads these files locally and makes no logo-related network requests at runtime.

| Bundled file | Original source | Processing for this package |
| --- | --- | --- |
| `logos/codex.png` | [OpenAI logomark SVG in the official OpenAI Cookbook](https://github.com/openai/openai-cookbook/blob/main/examples/agents_sdk/deployment_manager/frontend/src/openai-logomark.svg) | Rendered as a 72 × 72 transparent PNG with the white mark for DynamicLake's dark surface. OpenAI's [brand guidelines](https://openai.com/brand/) apply. |
| `logos/claude.png` | [Claude favicon](https://claude.ai/favicon.ico) | Extracted the 48 × 48 PNG representation from the official icon file. |
| `logos/opencode.png` | [OpenCode touch icon](https://opencode.ai/apple-touch-icon-v3.png) | Bundled the 180 × 180 PNG without visual changes. |

The package's existing `icon.png` predates version 1.4.0. Its original artwork source is not documented in this checkout; this release leaves it unchanged. No license for that artwork or for third-party marks is granted by this file.
