"""Report Hangul in tracked UTF-8 files without inspecting secrets or generated output.

Run with --json for a machine-readable inventory or --check to fail when any
tracked file contains Hangul. Historical migrations remain visible in the report.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path

HANGUL = re.compile(r"[\u1100-\u11ff\u3130-\u318f\ua960-\ua97f\uac00-\ud7af\ud7b0-\ud7ff]")


def scan(root: Path) -> list[dict[str, object]]:
    """Return paths, line numbers and counts; never print file contents."""
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git is required to scan tracked files")
    # Arguments are constant; the executable is resolved from the local PATH.
    tracked = subprocess.check_output([git, "ls-files", "-z"], cwd=root).decode().split("\0")  # noqa: S603
    inventory: list[dict[str, object]] = []
    for relative in sorted(filter(None, tracked)):
        path = root / relative
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        matches = HANGUL.findall(content)
        if not matches:
            continue
        inventory.append(
            {
                "path": relative,
                "characters": len(matches),
                "lines": [
                    i for i, line in enumerate(content.splitlines(), 1) if HANGUL.search(line)
                ],
            }
        )
    return inventory


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print the full inventory as JSON")
    parser.add_argument("--check", action="store_true", help="Exit with status 1 if Hangul remains")
    args = parser.parse_args()
    inventory = scan(Path(__file__).resolve().parents[1])
    if args.json:
        print(json.dumps(inventory, ensure_ascii=False, indent=2))
    else:
        for item in inventory:
            print(f"{item['path']}: {item['characters']} characters, {len(item['lines'])} lines")
        count = sum(int(item["characters"]) for item in inventory)
        print(f"Total: {len(inventory)} files, {count} characters")
    return int(args.check and bool(inventory))


if __name__ == "__main__":
    raise SystemExit(main())
