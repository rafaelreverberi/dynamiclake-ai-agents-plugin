# Asset provenance

The bundled agent marks identify the monitored products. They remain the property of their respective owners; their inclusion does not imply affiliation or endorsement. The plugin loads these files locally and makes no logo-related network requests at runtime.

| Bundled file | Original source | Processing for this package |
| --- | --- | --- |
| `logos/chatgpt.png` | [OpenAI logomark SVG in the official OpenAI Cookbook](https://github.com/openai/openai-cookbook/blob/main/examples/agents_sdk/deployment_manager/frontend/src/openai-logomark.svg) | Existing 72 × 72 transparent PNG, relabeled for the ChatGPT dropdown choice. OpenAI's [brand guidelines](https://openai.com/brand/) apply. |
| `logos/codex.png` | Codex PNG supplied by the user for this update; [OpenAI identifies the Codex app icon](https://openai.com/index/chatgpt-for-your-most-ambitious-work/) | Downsampled to 128 × 128 PNG. The supplied image already has a transparent background; its cloud shape and transparent symbol cutouts were preserved. |
| `logos/claude.png` | [Claude favicon](https://claude.ai/favicon.ico) | Extracted the 48 × 48 PNG representation from the official icon file. |
| `logos/claude-code.png` | Claude Code `color.svg` supplied by the user for this update | Rendered to 128 × 128 transparent PNG without changing the SVG's shape or color. |
| `logos/opencode.png` | [OpenCode touch icon](https://opencode.ai/apple-touch-icon-v3.png) | Bundled the 180 × 180 PNG without visual changes. |

The package's existing `icon.png` predates version 1.4.0. Its original artwork source is not documented in this checkout; this release leaves it unchanged. No license for that artwork or for third-party marks is granted by this file.
