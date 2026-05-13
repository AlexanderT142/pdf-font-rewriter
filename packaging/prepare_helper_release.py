from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST_ROOT = ROOT / "dist" / "helper"
RELEASE_ROOT = ROOT / "release" / "helper"
PYPROJECT = ROOT / "pyproject.toml"


def main() -> None:
    args = parse_args()
    version = args.version or project_version()
    release_dir = args.output or RELEASE_ROOT

    if args.clean:
        shutil.rmtree(release_dir, ignore_errors=True)
    release_dir.mkdir(parents=True, exist_ok=True)

    assets: dict[str, dict[str, object]] = {}
    for platform_dir in sorted(path for path in DIST_ROOT.iterdir() if path.is_dir()):
        binary = find_helper_binary(platform_dir)
        if not binary:
            continue

        platform_tag = platform_dir.name
        suffix = ".exe" if binary.suffix == ".exe" else ""
        release_name = f"refont-helper-{platform_tag}{suffix}"
        release_binary = release_dir / release_name
        shutil.copy2(binary, release_binary)

        if suffix != ".exe":
            release_binary.chmod(0o755)

        assets[platform_tag] = {
            "name": release_name,
            "platform": platform_tag,
            "sha256": sha256(release_binary),
            "size_bytes": release_binary.stat().st_size,
        }

    if not assets:
        raise SystemExit(f"no helper binaries found under {DIST_ROOT}")

    manifest = {
        "version": version,
        "assets": assets,
    }
    manifest_path = release_dir / "helper-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(manifest_path)
    for asset in assets.values():
        print(release_dir / str(asset["name"]))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare helper assets for a GitHub release.")
    parser.add_argument("--version", help="Helper version to write into helper-manifest.json.")
    parser.add_argument("--output", type=Path, help="Output directory for release assets.")
    parser.add_argument("--clean", action="store_true", help="Clear the output directory first.")
    return parser.parse_args()


def project_version() -> str:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def find_helper_binary(platform_dir: Path) -> Path | None:
    for name in ("refont-helper", "refont-helper.exe"):
        candidate = platform_dir / name
        if candidate.exists():
            return candidate
    return None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    main()
