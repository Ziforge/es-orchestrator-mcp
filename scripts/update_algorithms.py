#!/usr/bin/env python3
"""Fetch latest algorithm metadata from thorinside/nt_helper and update data/nt_algorithms.json.

Requires: gh CLI authenticated with GitHub.
Usage: python scripts/update_algorithms.py
"""

import base64
import json
import subprocess
import sys
from pathlib import Path

REPO = "thorinside/nt_helper"
ALGORITHMS_PATH = "docs/algorithms"
OUTPUT = Path(__file__).parent.parent / "data" / "nt_algorithms.json"


def gh_api(endpoint: str) -> str:
    result = subprocess.run(
        ["gh", "api", endpoint],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh api failed: {result.stderr}")
    return result.stdout


def main() -> None:
    print(f"Fetching algorithm list from {REPO}/{ALGORITHMS_PATH}...")
    listing = json.loads(gh_api(f"repos/{REPO}/contents/{ALGORITHMS_PATH}"))
    json_files = [f for f in listing if f["name"].endswith(".json")]
    print(f"Found {len(json_files)} algorithm files")

    algorithms = []
    errors = []

    for i, entry in enumerate(json_files):
        fname = entry["name"]
        try:
            file_data = json.loads(gh_api(f"repos/{REPO}/contents/{ALGORITHMS_PATH}/{fname}"))
            content = base64.b64decode(file_data["content"])
            algo = json.loads(content)
            algorithms.append(algo)
            if (i + 1) % 20 == 0:
                print(f"  Downloaded {i + 1}/{len(json_files)}...")
        except Exception as e:
            errors.append(f"{fname}: {e}")
            print(f"  ERROR: {fname}: {e}")

    print(f"\nDownloaded: {len(algorithms)} algorithms")
    if errors:
        print(f"Errors: {len(errors)}")
        for e in errors:
            print(f"  {e}")

    # Sort by GUID for stable diffs
    algorithms.sort(key=lambda a: a.get("guid", ""))

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w") as f:
        json.dump(algorithms, f, indent=2)
        f.write("\n")

    print(f"Written {OUTPUT} ({OUTPUT.stat().st_size:,} bytes, {len(algorithms)} algorithms)")

    # Check if anything changed
    try:
        diff = subprocess.run(
            ["git", "diff", "--stat", str(OUTPUT)],
            capture_output=True, text=True, cwd=OUTPUT.parent.parent,
        )
        if diff.stdout.strip():
            print(f"\nChanges detected:\n{diff.stdout}")
        else:
            print("\nNo changes — already up to date.")
    except Exception:
        pass


if __name__ == "__main__":
    main()
