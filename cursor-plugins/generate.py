#!/usr/bin/env python3
"""Copy shared Cursor hook launchers into the plugins that use them.

Manifests and skill trees under cursor-plugins are maintained in place.
This script does not read a Claude marketplace.

    python cursor-plugins/generate.py
    python cursor-plugins/generate.py --check
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CURSOR = REPO / "cursor-plugins"
CHECK = "--check" in sys.argv[1:]

HOOK_COPIES = {
    "salesforce-development": ["cursor-hook.cjs"],
    "experience-lwc": ["cursor-hook.cjs", "cursor_advisory.py"],
    "agentforce-adlc": ["cursor-hook.cjs", "cursor_advisory.py"],
}


def expected() -> dict:
    files = {}
    lib = CURSOR / "tooling"
    for plugin, names in HOOK_COPIES.items():
        for filename in names:
            files[CURSOR / plugin / "hooks" / filename] = (
                lib / filename
            ).read_text(encoding="utf-8")
    return files


def normalized(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def main() -> int:
    files = expected()
    if CHECK:
        stale = [
            path
            for path, text in files.items()
            if not path.is_file() or normalized(path) != text
        ]
        if stale:
            print("Hook launchers are stale. Run python cursor-plugins/generate.py")
            for path in stale:
                print(f"  {path.relative_to(REPO)}")
            return 1
        print(f"Checked {len(files)} hook launchers")
        return 0
    for path, text in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    print(f"Wrote {len(files)} hook launchers under {CURSOR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
