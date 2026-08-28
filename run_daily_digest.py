#!/usr/bin/env python3
"""CLI for the weekday 8:30 AM IST morning digest.

Examples:
  python run_daily_digest.py --preview --quick
  python run_daily_digest.py --send
  python run_daily_digest.py --preview --to you@example.com
"""

from __future__ import annotations

import argparse
import json
import sys

from digest import DEFAULT_TOP_N, run_digest


def main() -> int:
    parser = argparse.ArgumentParser(description="FunTech top scores")
    parser.add_argument("--preview", action="store_true", help="Write HTML to digest_outbox/ (default if --send is omitted)")
    parser.add_argument("--send", action="store_true", help="Email opted-in subscribers when SMTP is configured")
    parser.add_argument("--quick", action="store_true", help="Nifty 50 + Next 50 fallback lists only (fast local preview)")
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N, help="Number of stocks per group/index (default 10)")
    parser.add_argument("--to", action="append", default=[], help="Extra recipient (repeatable)")
    parser.add_argument("--force-weekend", action="store_true", help="Run even on Saturday/Sunday")
    args = parser.parse_args()

    result = run_digest(
        quick=args.quick,
        send=args.send,
        extra_recipients=args.to,
        top_n=args.top_n,
        skip_weekends=not args.force_weekend and args.send,
    )
    printable = {k: v for k, v in result.items() if k != "html"}
    print(json.dumps(printable, indent=2, default=str))
    if result.get("outbox_path"):
        print(f"\nPreview file: {result['outbox_path']}")
    status = result.get("status")
    if status == "skipped-weekend":
        return 0
    if status == "no-subscribers":
        print("No opted-in subscribers and no --to / DIGEST_TO / SMTP_FROM recipient.", file=sys.stderr)
        return 1
    if not args.send:
        return 0 if status == "ok" else 1
    sent = any(d.get("status") == "sent" for d in (result.get("deliveries") or []))
    if sent:
        return 0
    print("SMTP did not deliver any message. Check SMTP_* secrets and the deliveries list above.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
