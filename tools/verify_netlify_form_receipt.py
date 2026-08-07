#!/usr/bin/env python3
"""Verify an exact Netlify form receipt without exposing submission contents."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

API_BASE = "https://api.netlify.com/api/v1"
MARKER_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")


def request_json(url: str, token: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def marker_matches(submission: dict[str, Any], marker: str) -> bool:
    candidates: list[str] = []
    data = submission.get("data")
    if isinstance(data, dict):
        candidates.extend(str(value) for value in data.values() if value is not None)
    for key in ("summary", "body"):
        value = submission.get(key)
        if isinstance(value, str):
            candidates.append(value)
    return any(marker in candidate for candidate in candidates)


def build_report(
    submissions: list[dict[str, Any]],
    hooks: list[dict[str, Any]],
    marker: str,
    require_email_hook: bool,
) -> dict[str, Any]:
    matches = [entry for entry in submissions if marker_matches(entry, marker)]
    matches.sort(key=lambda entry: str(entry.get("created_at", "")), reverse=True)
    enabled_submission_hooks = [
        hook
        for hook in hooks
        if not hook.get("disabled", False)
        and "submission" in str(hook.get("event", "")).lower()
    ]
    enabled_email_hooks = [
        hook
        for hook in enabled_submission_hooks
        if "email" in str(hook.get("type", "")).lower()
    ]

    result = "pass"
    reason = "Exact marker found in Netlify submissions."
    if not matches:
        result = "fail"
        reason = "Exact marker was not found in the latest Netlify submissions."
    elif require_email_hook and not enabled_email_hooks:
        result = "attention"
        reason = "Submission found, but no enabled Netlify email notification hook was found."

    receipt: dict[str, Any] | None = None
    if matches:
        latest = matches[0]
        identifier = str(latest.get("id", ""))
        receipt = {
            "createdAt": latest.get("created_at"),
            "submissionIdSha256": hashlib.sha256(identifier.encode("utf-8")).hexdigest()
            if identifier
            else None,
        }

    return {
        "result": result,
        "reason": reason,
        "marker": marker,
        "matchCount": len(matches),
        "receipt": receipt,
        "notifications": {
            "enabledSubmissionHooks": len(enabled_submission_hooks),
            "enabledEmailHooks": len(enabled_email_hooks),
            "enabledHookTypes": sorted(
                {str(hook.get("type", "unknown")) for hook in enabled_submission_hooks}
            ),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-id", required=True)
    parser.add_argument("--marker", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--per-page", type=int, default=100)
    parser.add_argument("--require-email-hook", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not MARKER_PATTERN.fullmatch(args.marker):
        raise SystemExit("Marker must be 8-128 characters using letters, numbers, . _ : or -")
    if not 1 <= args.per_page <= 100:
        raise SystemExit("--per-page must be between 1 and 100")
    token = os.environ.get("NETLIFY_AUTH_TOKEN", "")
    if not token:
        raise SystemExit("NETLIFY_AUTH_TOKEN is required")

    site_id = urllib.parse.quote(args.site_id, safe="")
    submissions = request_json(
        f"{API_BASE}/sites/{site_id}/submissions?per_page={args.per_page}", token
    )
    hooks = request_json(f"{API_BASE}/hooks?site_id={site_id}", token)
    if not isinstance(submissions, list) or not isinstance(hooks, list):
        raise SystemExit("Netlify API returned an unexpected response")

    report = build_report(submissions, hooks, args.marker, args.require_email_hook)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return {"pass": 0, "fail": 1, "attention": 2}[report["result"]]


if __name__ == "__main__":
    sys.exit(main())
