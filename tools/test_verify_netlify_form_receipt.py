#!/usr/bin/env python3
"""Regression tests for privacy-safe Netlify form receipt verification."""

from __future__ import annotations

import unittest

import verify_netlify_form_receipt


class FormReceiptTests(unittest.TestCase):
    marker = "RD-QA-20260718-02b0928"

    def test_exact_marker_and_email_hook_pass(self) -> None:
        report = verify_netlify_form_receipt.build_report(
            [
                {
                    "id": "submission-secret-id",
                    "created_at": "2026-07-19T02:03:19Z",
                    "email": "private@example.com",
                    "data": {"goal": f"Please ignore {self.marker}"},
                }
            ],
            [{"type": "email", "event": "submission_created", "disabled": False}],
            self.marker,
            True,
        )

        self.assertEqual(report["result"], "pass")
        self.assertEqual(report["matchCount"], 1)
        self.assertEqual(report["notifications"]["enabledEmailHooks"], 1)
        self.assertNotIn("email", report["receipt"])
        self.assertNotIn("data", report["receipt"])
        self.assertNotEqual(report["receipt"]["submissionIdSha256"], "submission-secret-id")

    def test_missing_marker_fails(self) -> None:
        report = verify_netlify_form_receipt.build_report(
            [{"data": {"goal": "unrelated"}}], [], self.marker, False
        )
        self.assertEqual(report["result"], "fail")
        self.assertIsNone(report["receipt"])

    def test_missing_required_email_hook_needs_attention(self) -> None:
        report = verify_netlify_form_receipt.build_report(
            [{"data": {"goal": self.marker}}],
            [{"type": "slack", "event": "submission_created", "disabled": False}],
            self.marker,
            True,
        )
        self.assertEqual(report["result"], "attention")
        self.assertEqual(report["notifications"]["enabledEmailHooks"], 0)

    def test_disabled_email_hook_does_not_count(self) -> None:
        report = verify_netlify_form_receipt.build_report(
            [{"body": self.marker}],
            [{"type": "email", "event": "submission_created", "disabled": True}],
            self.marker,
            True,
        )
        self.assertEqual(report["result"], "attention")


if __name__ == "__main__":
    unittest.main()
