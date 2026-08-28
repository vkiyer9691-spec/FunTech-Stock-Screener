#!/usr/bin/env python3
"""Dispatch the Daily morning scores GitHub Action (workflow_dispatch).

Used by an external clock (Supabase pg_cron, cron-job.org, or this script).
GitHub's own workflow `schedule:` event is not used as the primary timer.

  export GITHUB_TOKEN=...   # PAT with Actions: write
  python scripts/trigger_morning_scores.py
  python scripts/trigger_morning_scores.py --quick
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

REPO = "vkiyer9691-spec/FunTech-Stock-Screener"
WORKFLOW = "morning-digest.yml"


def main() -> int:
    parser = argparse.ArgumentParser(description="Dispatch FunTech daily morning scores")
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--ref", default="main")
    args = parser.parse_args()
    token = (os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_PAT") or "").strip()
    if not token:
        print("Set GITHUB_TOKEN to a PAT with Actions: write.", file=sys.stderr)
        return 2
    url = f"https://api.github.com/repos/{REPO}/actions/workflows/{WORKFLOW}/dispatches"
    body = json.dumps({"ref": args.ref, "inputs": {"quick": "true" if args.quick else "false"}}).encode()
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "funtech-morning-scores",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            print(f"dispatch {resp.status}")
            return 0
    except urllib.error.HTTPError as exc:
        print(exc.read().decode()[:800], file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
