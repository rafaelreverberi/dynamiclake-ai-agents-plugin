"""Build the self-contained macOS runtime from pinned, verified inputs."""

import hashlib
from importlib.metadata import Distribution
import os
from pathlib import Path
import shutil
import subprocess
import sys

CPYTHON = "3.14.10"
CPYTHON_SHA256 = "de414a57119abef52784d8993e341d53aed635fc2b05c2607d9f98a2c5b72032"
MIN_MACOS = "11.0"
TOOL_REQUIREMENTS = Path(__file__).with_name("market-build-requirements.txt")

# The runtime uses local JSON, SQLite, Unix sockets and provider CLI processes.
# Avoid collecting optional dependency trees reached through the standard library
# (e.g. email, network TLS, package metadata or GUI support).
EXCLUDED = (
    "_hashlib", "compression.zstd", "ctypes", "decimal", "email",
    "importlib.metadata", "lzma", "multiprocessing", "pydoc", "ssl",
    "tkinter", "unicodedata", "unittest", "urllib.request",
)


def build_runtime(package: Path, work: Path, name: str) -> Path:
    if sys.platform != "darwin":
        raise ValueError("The universal2 release must be built on macOS")
    sdk = subprocess.check_output(["xcrun", "--show-sdk-path"], text=True).strip()
    env = {**os.environ, "SDKROOT": sdk, "MACOSX_DEPLOYMENT_TARGET": MIN_MACOS,
           "CFLAGS": "-Os", "PKG_CONFIG": "/usr/bin/false",
           "LIBSQLITE3_CFLAGS": f"-I{sdk}/usr/include", "LIBSQLITE3_LIBS": "-lsqlite3"}
    for key in ("PYTHONHOME", "PYTHONPATH", "DYLD_LIBRARY_PATH", "CPPFLAGS", "LDFLAGS",
                "CXXFLAGS", "CONFIG_SITE"):
        env.pop(key, None)

    archive = work / f"Python-{CPYTHON}.tar.xz"
    subprocess.run(["curl", "-fsSL", "--retry", "2", "-o", str(archive),
                    f"https://www.python.org/ftp/python/{CPYTHON}/{archive.name}"], check=True)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != CPYTHON_SHA256:
        raise ValueError("CPython source checksum mismatch")
    subprocess.run(["tar", "-xf", str(archive), "-C", str(work)], check=True)
    source = work / f"Python-{CPYTHON}"
    subprocess.run(["./configure", f"--prefix={work / 'install'}", f"--enable-universalsdk={sdk}",
                    "--with-universal-archs=universal2", "--enable-shared", "--without-ensurepip",
                    "--without-readline", "--with-system-expat"], cwd=source, env=env, check=True)
    subprocess.run(["make", f"-j{min(os.cpu_count() or 2, 8)}"], cwd=source, env=env, check=True)
    installed = work / "install"
    subprocess.run(["make", "install"], cwd=source, env=env, check=True)

    # Build tools go in a private directory. No install into system Python or CPython.
    tools = work / "tools"
    subprocess.run([sys.executable, "-m", "pip", "install", "--only-binary=:all:",
                    "--require-hashes", "--target", str(tools), "-r", str(TOOL_REQUIREMENTS)],
                   env=env, check=True)
    env.update({"PYTHONPATH": str(tools), "PYINSTALLER_CONFIG_DIR": str(work / "cache"),
                "PYTHONHASHSEED": "0"})
    flags = [arg for module in EXCLUDED for arg in ("--exclude-module", module)]
    # Onedir lets the ZIP compress the runtime directly and avoids temporary
    # extraction every time a provider invokes a short-lived hook.
    subprocess.run([str(installed / "bin" / "python3.14"), "-m", "PyInstaller", "--target-arch",
                    "universal2", "--onedir", "--strip", "--noupx", "--name", name,
                    "--distpath", str(work / "output"), "--workpath", str(work / "freeze"),
                    "--specpath", str(work), *flags, str(package / "ai-agents-monitor.py")],
                   cwd=work, env=env, check=True)
    runtime = work / "output" / name
    licenses = runtime / "licenses"
    licenses.mkdir()
    shutil.copyfile(source / "LICENSE", licenses / "CPython.txt")
    distributions = {d.metadata["Name"].lower(): d for d in Distribution.discover(path=[str(tools)])}
    # PyInstaller's embedded inspect hook is Apache 2.0; the packaging tool's
    # wheel provides the unmodified text of that license.
    for project, filename, target in (("pyinstaller", "COPYING.txt", "PyInstaller.txt"),
                                      ("packaging", "LICENSE.APACHE", "Apache-2.0.txt")):
        dist = distributions[project]
        path = next(p for p in dist.files if p.name == filename)
        shutil.copyfile(dist.locate_file(path), licenses / target)
    return runtime
