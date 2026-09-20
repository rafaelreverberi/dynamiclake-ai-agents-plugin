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
    require(len(settings) == 2 and {setting["id"] for setting in settings} == {"enableOpenCode", "showAgentLogos"}, "Unexpected settings")

    executable = PACKAGE / manifest["executable"]
    icon = PACKAGE / manifest["icon"]
    require(executable.is_file() and os.access(executable, os.X_OK), "Plugin executable is missing or not executable")
    require(icon.is_file() and icon.stat().st_size <= MAX_ICON_BYTES, "Package icon is missing or too large")
    compile(executable.read_bytes(), str(executable), "exec")
    for name in ("codex.png", "claude.png", "opencode.png"):
        path = PACKAGE / "logos" / name
        require(path.is_file(), f"Missing logo: {name}")
        data = path.read_bytes()
        require(data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) <= MAX_INLINE_IMAGE_BYTES, f"Invalid or oversized logo: {name}")

    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=ROOT, env=env, check=True)

    files = sorted(
        path for path in PACKAGE.rglob("*")
        if path.is_file() and not path.name.startswith(".") and path.suffix != ".pyc"
        and "__pycache__" not in path.parts
    )
    require(sum(path.stat().st_size for path in files) <= MAX_PACKAGE_BYTES, "Extracted package exceeds 20 MB")
    output_dir = ROOT / "dist"
    output_dir.mkdir(exist_ok=True)
    archive = output_dir / f"AI-Agents-{version}.zip"
    temporary = output_dir / f".AI-Agents-{version}.zip.tmp"
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path in files:
            bundle.write(path, arcname=str(path.relative_to(ROOT)))
    with zipfile.ZipFile(temporary) as bundle:
        require(bundle.testzip() is None, "ZIP integrity check failed")
        names = set(bundle.namelist())
        require(f"{PACKAGE.name}/plugin.json" in names, "Plugin manifest missing from ZIP")
        member = bundle.getinfo(f"{PACKAGE.name}/{executable.name}")
        require(stat.S_IMODE(member.external_attr >> 16) & stat.S_IXUSR, "Executable bit missing from ZIP")
    require(temporary.stat().st_size <= MAX_ARCHIVE_BYTES, "Archive exceeds 7 MB")
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
