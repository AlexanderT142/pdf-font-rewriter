from __future__ import annotations

import argparse
import json
import re
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
PLUGIN_PACKAGE = ROOT / "obsidian-plugin" / "package.json"
PLUGIN_MANIFEST = ROOT / "obsidian-plugin" / "manifest.json"
PLUGIN_VERSIONS = ROOT / "obsidian-plugin" / "versions.json"
ROOT_MANIFEST = ROOT / "manifest.json"
ROOT_VERSIONS = ROOT / "versions.json"
HELPER_RELEASE_TS = ROOT / "obsidian-plugin" / "src" / "helperRelease.ts"


def main() -> None:
    args = parse_args()
    pyproject_version = pyproject_project_version()
    package_version = json_version(PLUGIN_PACKAGE)
    manifest_version = json_version(PLUGIN_MANIFEST)
    versions_map = json.loads(PLUGIN_VERSIONS.read_text(encoding="utf-8"))
    root_manifest_version = json_version(ROOT_MANIFEST)
    root_versions_map = json.loads(ROOT_VERSIONS.read_text(encoding="utf-8"))
    helper_version = helper_ts_value("HELPER_VERSION")
    helper_base_url = helper_ts_value("DEFAULT_HELPER_RELEASE_BASE_URL")

    expected = args.version or pyproject_version
    tag = args.tag
    if tag:
        assert_equal("release tag", tag, expected)

    assert_equal("pyproject version", pyproject_version, expected)
    assert_equal("obsidian package version", package_version, expected)
    assert_equal("obsidian manifest version", manifest_version, expected)
    assert_equal("root manifest version", root_manifest_version, expected)
    assert_equal("helper version", helper_version, expected)
    assert_equal("root manifest", ROOT_MANIFEST.read_text(encoding="utf-8"), PLUGIN_MANIFEST.read_text(encoding="utf-8"))
    assert_equal("root versions", ROOT_VERSIONS.read_text(encoding="utf-8"), PLUGIN_VERSIONS.read_text(encoding="utf-8"))

    if expected not in versions_map:
        raise SystemExit(f"versions.json does not contain {expected}")
    if expected not in root_versions_map:
        raise SystemExit(f"root versions.json does not contain {expected}")

    if not helper_base_url.endswith(f"/download/{expected}"):
        raise SystemExit(
            "DEFAULT_HELPER_RELEASE_BASE_URL must end with "
            f"/download/{expected}; got {helper_base_url}"
        )

    print(f"release versions OK: {expected}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check release version consistency.")
    parser.add_argument("--version", help="Expected release version.")
    parser.add_argument("--tag", help="Git tag name, for example 0.1.0.")
    return parser.parse_args()


def pyproject_project_version() -> str:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def json_version(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    return str(data["version"])


def helper_ts_value(name: str) -> str:
    source = HELPER_RELEASE_TS.read_text(encoding="utf-8")
    pattern = rf'export const {re.escape(name)}\s*=\s*"([^"]+)";'
    match = re.search(pattern, source)
    if not match:
        raise SystemExit(f"could not find {name} in {HELPER_RELEASE_TS}")
    return match.group(1)


def assert_equal(label: str, actual: str, expected: str) -> None:
    if actual != expected:
        raise SystemExit(f"{label} mismatch: expected {expected}, got {actual}")


if __name__ == "__main__":
    main()
