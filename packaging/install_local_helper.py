from __future__ import annotations

import argparse
import platform
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST_ROOT = ROOT / "dist" / "helper"
APP_NAME = "pdf-font-rewriter"


def main() -> None:
    args = parse_args()
    tag = args.platform_tag or current_platform_tag()
    source = DIST_ROOT / tag / executable_name()
    if not source.exists():
        raise SystemExit(f"helper binary not found: {source}")

    target = args.target or default_helper_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    target.chmod(0o755)
    print(target)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install the local helper binary into the OS app-data path.")
    parser.add_argument("--platform-tag", help="Override the source platform tag.")
    parser.add_argument("--target", type=Path, help="Override helper install path.")
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


def default_helper_path() -> Path:
    home = Path.home()
    system = platform.system().lower()

    if system == "darwin":
        return home / "Library" / "Application Support" / APP_NAME / "bin" / executable_name()
    if system == "windows":
        appdata = Path.home() / "AppData" / "Roaming"
        return appdata / APP_NAME / "bin" / executable_name()
    return home / ".local" / "share" / APP_NAME / "bin" / executable_name()


if __name__ == "__main__":
    main()
