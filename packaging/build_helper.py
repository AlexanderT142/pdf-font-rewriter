from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "packaging" / "refont_helper_entry.py"
DIST_ROOT = ROOT / "dist" / "helper"
BUILD_ROOT = ROOT / "build" / "pyinstaller"


def main() -> None:
    args = parse_args()
    tag = args.platform_tag or current_platform_tag()
    dist_dir = DIST_ROOT / tag
    work_dir = BUILD_ROOT / tag

    if args.clean:
        shutil.rmtree(dist_dir, ignore_errors=True)
        shutil.rmtree(work_dir, ignore_errors=True)

    dist_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        executable_name(),
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(work_dir),
        "--specpath",
        str(work_dir),
        "--collect-all",
        "fitz",
        "--collect-all",
        "pymupdf",
        str(ENTRY),
    ]
    subprocess.run(command, cwd=ROOT, check=True)

    binary = dist_dir / executable_name()
    metadata = {
        "name": binary.name,
        "platform": tag,
        "sha256": sha256(binary),
        "size_bytes": binary.stat().st_size,
    }
    metadata_path = dist_dir / f"{binary.name}.sha256.json"
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    print(binary)
    print(metadata_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the packaged refont helper binary.")
    parser.add_argument("--platform-tag", help="Override the output platform tag.")
    parser.add_argument("--clean", action="store_true", help="Remove previous build output first.")
    return parser.parse_args()


def current_platform_tag() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "darwin":
        os_name = "macos"
    elif system == "windows":
        os_name = "windows"
    elif system == "linux":
        os_name = "linux"
    else:
        os_name = system

    if machine in {"arm64", "aarch64"}:
        arch = "arm64"
    elif machine in {"x86_64", "amd64"}:
        arch = "x64"
    else:
        arch = machine.replace(" ", "-")

    return f"{os_name}-{arch}"


def executable_name() -> str:
    return "refont-helper.exe" if platform.system().lower() == "windows" else "refont-helper"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    main()
