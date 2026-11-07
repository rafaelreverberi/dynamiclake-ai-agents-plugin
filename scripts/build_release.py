#!/usr/bin/env python3
"""Validate and package the local DynamicLake plugin for distribution."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "AIAgents.dynamiclakeplugin"
MANIFEST = PACKAGE / "plugin.json"
MAX_ARCHIVE_BYTES = 7_000_000
MAX_PACKAGE_BYTES = 20_000_000
MAX_MANIFEST_BYTES = 128_000
MAX_ICON_BYTES = 1_500_000
MAX_INLINE_IMAGE_BYTES = 48_000


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def main() -> int:
    manifest_bytes = MANIFEST.read_bytes()
    require(len(manifest_bytes) <= MAX_MANIFEST_BYTES, "plugin.json exceeds 128 KB")
    manifest = json.loads(manifest_bytes)
    require(manifest.get("schemaVersion") == 1, "Unexpected manifest schema")
    require(manifest.get("identifier") == "com.dynamiclake.plugins.ai-agents", "Unexpected plugin ID")
    require(manifest.get("developerName") == "Rafael Reverberi", "Unexpected developer name")
    version = manifest.get("version")
    require(isinstance(version, str) and version, "Missing package version")
    require(f"## {version} " in (ROOT / "CHANGELOG.md").read_text(), "Changelog lacks this version")
    settings = manifest.get("settings", [])
    require(len(settings) <= 24 and len({s['id'] for s in settings}) == len(settings), "Invalid settings count or duplicate IDs")
    require({"enableOpenCode", "enableHooks", "interactiveApprovals", "enableUsageTracking", "codexLogo", "claudeLogo"} <= {s['id'] for s in settings}, "Missing settings")
    require(manifest.get("lake", {}).get("size") == "big", "Missing full lake declaration")
    for setting_id, choices, default in (
        ("codexLogo", {"ChatGPT", "Codex"}, "Codex"),
        ("claudeLogo", {"Claude", "Claude Code"}, "Claude Code"),
    ):
        setting = next(item for item in settings if item["id"] == setting_id)
        require(setting.get("type") == "select" and {option.get("title") for option in setting.get("options", [])} == choices and setting.get("default") == default, f"Invalid {setting_id} dropdown")

    executable = PACKAGE / manifest["executable"]
    icon = PACKAGE / manifest["icon"]
    require(executable.is_file() and os.access(executable, os.X_OK), "Plugin executable is missing or not executable")
    require(icon.is_file() and icon.stat().st_size <= MAX_ICON_BYTES, "Package icon is missing or too large")
    for source in PACKAGE.glob("*.py"):
        compile(source.read_bytes(), str(source), "exec")
    for name in ("chatgpt.png", "codex.png", "claude.png", "claude-code.png", "opencode.png"):
        path = PACKAGE / "logos" / name
        require(path.is_file(), f"Missing logo: {name}")
        data = path.read_bytes()
        require(data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) <= MAX_INLINE_IMAGE_BYTES, f"Invalid or oversized logo: {name}")

    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=ROOT, env=env, check=True)

    # Explicit package allowlist excludes caches and accidental user data.
    files = sorted([PACKAGE / "plugin.json", PACKAGE / "icon.png"] + list(PACKAGE.glob("*.py"))
                   + list((PACKAGE / "logos").glob("*.png")) + list(PACKAGE.glob("*.md"))
                   + [PACKAGE / "opencode-approvals" / "index.js"])
    docs = [ROOT / name for name in ("README.md", "PRIVACY.md", "SECURITY.md", "ASSETS.md", "CHANGELOG.md", "RELEASING.md")]
    docs += sorted((ROOT / "docs").glob("*.md"))
    entries = [(path, str(path.relative_to(ROOT))) for path in files]
    entries += [(path, PACKAGE.name + "/" + str(path.relative_to(ROOT))) for path in docs]
    entries.sort(key=lambda item: item[1])
    require(all(not path.is_symlink() for path in files), "Symlinked package member")
    require(sum(path.stat().st_size for path, _ in entries) <= MAX_PACKAGE_BYTES, "Extracted package exceeds 20 MB")
    output_dir = ROOT / "dist"
    output_dir.mkdir(exist_ok=True)
    archive = output_dir / f"AI-Agents-{version}.zip"
    temporary = output_dir / f".AI-Agents-{version}.zip.tmp"
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path, archive_name in entries:
            member = zipfile.ZipInfo(archive_name, date_time=(2026, 11, 6, 0, 0, 0))
            member.compress_type = zipfile.ZIP_DEFLATED
            member.create_system = 3
            member.external_attr = (stat.S_IFREG | (0o755 if os.access(path, os.X_OK) else 0o644)) << 16
            bundle.writestr(member, path.read_bytes(), compresslevel=9)
    with zipfile.ZipFile(temporary) as bundle:
        require(bundle.testzip() is None, "ZIP integrity check failed")
        names = set(bundle.namelist())
        require(f"{PACKAGE.name}/plugin.json" in names, "Plugin manifest missing from ZIP")
        member = bundle.getinfo(f"{PACKAGE.name}/{executable.name}")
        require(stat.S_IMODE(member.external_attr >> 16) & stat.S_IXUSR, "Executable bit missing from ZIP")
    require(temporary.stat().st_size <= MAX_ARCHIVE_BYTES, "Archive exceeds 7 MB")
    # Exercise the extracted executable with isolated provider roots and HOME.
    import tempfile
    with tempfile.TemporaryDirectory() as directory:
        extracted = Path(directory)
        with zipfile.ZipFile(temporary) as bundle:
            bundle.extractall(extracted)
        isolated = env.copy()
        isolated.update({"HOME": directory, "CODEX_HOME": str(extracted / "codex"),
                         "CLAUDE_HOME": str(extracted / "claude"), "XDG_DATA_HOME": str(extracted / "data"),
                         "DYNAMICLAKE_PLUGIN_SETTINGS_PATH": str(extracted / "no-settings.json"),
                         "OPENCODE_DB": str(extracted / "absent.db")})
        output = subprocess.check_output([sys.executable, str(extracted / PACKAGE.name / executable.name), "--check"], env=isolated, text=True)
        require(json.loads(output)["active"] == 0, "Extracted plugin check failed")
        require(not list((extracted / PACKAGE.name).rglob("*.pyc")), "Plugin wrote bytecode into package")
    subprocess.run([sys.executable, str(ROOT / "scripts/smoke_package.py"), str(temporary)], env=env, check=True)
    temporary.replace(archive)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksum = archive.with_suffix(".zip.sha256")
    checksum.write_text(f"{digest}  {archive.name}\n")
    print(f"Created {archive} ({archive.stat().st_size:,} bytes)")
    print(f"SHA-256: {digest}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Package build failed: {error}", file=sys.stderr)
        raise SystemExit(1)
