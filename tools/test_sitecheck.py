#!/usr/bin/env python3
"""Regression tests for the reusable website-operations verifier."""

from __future__ import annotations

import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import sitecheck


class InspectorTests(unittest.TestCase):
    def test_image_with_src_and_without_alt_is_reported(self) -> None:
        page = sitecheck.parse_html("test", b'<html lang="en"><img src="/image.png"></html>')
        self.assertEqual(page.missing_alt, ["/image.png"])

    def test_empty_alt_is_allowed_for_decorative_image(self) -> None:
        page = sitecheck.parse_html("test", b'<html lang="en"><img src="/image.png" alt=""></html>')
        self.assertEqual(page.missing_alt, [])


class ContractTests(unittest.TestCase):
    def test_nested_index_path_mapping(self) -> None:
        self.assertEqual(sitecheck.path_for_html("index.html"), "/")
        self.assertEqual(sitecheck.path_for_html("about.html"), "/about")
        self.assertEqual(sitecheck.path_for_html("about.html", keep_html_extension=True), "/about.html")
        self.assertEqual(sitecheck.path_for_html("blog/fuel-fasting/index.html"), "/blog/fuel-fasting")
        self.assertEqual(sitecheck.path_for_html("blog/fuel-fasting/index.html", True), "/blog/fuel-fasting/")

    def test_source_supports_explicit_nested_html_globs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            nested = root / "blog" / "fuel-fasting"
            nested.mkdir(parents=True)
            (root / "index.html").write_text(
                """<!doctype html><html lang="en"><head>
                <title>Home</title><meta name="description" content="Home page">
                <link rel="canonical" href="https://example.com/">
                </head><body><h1>Home</h1><a href="/blog/fuel-fasting">Read</a></body></html>""",
                encoding="utf-8",
            )
            (nested / "index.html").write_text(
                """<!doctype html><html lang="en"><head>
                <title>Fuel Fasting</title><meta name="description" content="Article page">
                <link rel="canonical" href="https://example.com/blog/fuel-fasting">
                </head><body><h1>Fuel Fasting</h1><a href="/">Home</a></body></html>""",
                encoding="utf-8",
            )
            (root / "sitemap.xml").write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
                <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                  <url><loc>https://example.com/</loc></url>
                  <url><loc>https://example.com/blog/fuel-fasting</loc></url>
                </urlset>""",
                encoding="utf-8",
            )
            config = {
                "canonicalBase": "https://example.com",
                "sitemapPath": "/sitemap.xml",
                "requiredSourceFiles": [],
                "sourceHtmlGlobs": ["*.html", "blog/*/index.html"],
                "sourceHtmlExcludedFromSitemap": [],
            }

            issues, summary = sitecheck.source_check(root, config)

            self.assertEqual(issues, [])
            self.assertEqual(summary["htmlPages"], 2)
            self.assertEqual(summary["sitemapUrls"], 2)

    def test_source_root_and_virtual_sitemap_paths_are_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_root = root / "canonical-site"
            source_root.mkdir()
            (root / "required.txt").write_text("repository contract", encoding="utf-8")
            (source_root / "index.html").write_text(
                """<!doctype html><html lang="en"><head>
                <title>Home</title><meta name="description" content="Home page">
                <link rel="canonical" href="https://example.com/">
                </head><body><h1>Home</h1><a href="/blog/worker-article/">Worker article</a></body></html>""",
                encoding="utf-8",
            )
            article = source_root / "blog" / "static-article"
            article.mkdir(parents=True)
            (article / "index.html").write_text(
                """<!doctype html><html lang="en"><head>
                <title>Static article</title><meta name="description" content="Static article page">
                <link rel="canonical" href="https://example.com/blog/static-article/">
                </head><body><h1>Static article</h1></body></html>""",
                encoding="utf-8",
            )
            (source_root / "sitemap.xml").write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
                <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                  <url><loc>https://example.com/</loc></url>
                  <url><loc>https://example.com/blog/static-article/</loc></url>
                  <url><loc>https://example.com/blog/worker-article/</loc></url>
                </urlset>""",
                encoding="utf-8",
            )
            config = {
                "canonicalBase": "https://example.com",
                "sitemapPath": "/sitemap.xml",
                "sourceRoot": "canonical-site",
                "requiredSourceFiles": ["required.txt"],
                "sourceHtmlGlobs": ["**/index.html"],
                "sourceHtmlExcludedFromSitemap": [],
                "sourceDirectoryIndexTrailingSlash": True,
                "sourceVirtualSitemapPaths": ["/blog/worker-article/"],
            }

            issues, summary = sitecheck.source_check(root, config)

            self.assertEqual(issues, [])
            self.assertEqual(summary["htmlPages"], 2)
            self.assertEqual(summary["sitemapUrls"], 3)
            self.assertEqual(summary["virtualSitemapUrls"], 1)
            self.assertEqual(summary["sourceRoot"], "canonical-site")

    def test_netlify_source_attribute_is_opt_in(self) -> None:
        page = sitecheck.parse_html(
            "contact.html",
            b'<form name="contact" method="post" action="/thanks"><input name="email" type="email" required></form>',
        )
        expected = {
            "name": "contact",
            "method": "post",
            "action": "/thanks",
            "fields": {"email": {"type": "email", "required": True}},
        }

        issues: list[sitecheck.Issue] = []
        sitecheck.check_form(page, expected, issues)
        self.assertNotIn("form.netlify", {issue.code for issue in issues})

        issues = []
        sitecheck.check_form(page, {**expected, "netlify": True}, issues)
        self.assertIn("form.netlify", {issue.code for issue in issues})

    def test_expected_headers_are_checked_on_each_page(self) -> None:
        page = sitecheck.Page(subject="/contact", headers={"x-content-type-options": "nosniff"})
        issues: list[sitecheck.Issue] = []
        sitecheck.check_expected_headers(
            page,
            {"expectedHeaders": {"x-content-type-options": "nosniff", "referrer-policy": "strict-origin"}},
            issues,
        )
        self.assertEqual([issue.code for issue in issues], ["http.header"])
        self.assertEqual(issues[0].subject, "/contact")

    def test_source_rejects_unexpected_sitemap_url(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "index.html").write_text(
                """<!doctype html><html lang="en"><head>
                <title>Test</title><meta name="description" content="Test page">
                <link rel="canonical" href="https://example.com/">
                </head><body><h1>Test</h1></body></html>""",
                encoding="utf-8",
            )
            (root / "sitemap.xml").write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
                <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                  <url><loc>https://example.com/</loc></url>
                  <url><loc>https://wrong.example/unexpected</loc></url>
                </urlset>""",
                encoding="utf-8",
            )
            config = {
                "canonicalBase": "https://example.com",
                "sitemapPath": "/sitemap.xml",
                "requiredSourceFiles": [],
                "sourceHtmlExcludedFromSitemap": [],
            }
            issues, _ = sitecheck.source_check(root, config)
            self.assertIn("sitemap.unexpected", {issue.code for issue in issues})

    def test_source_patterns_include_script_contents(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "index.html").write_text(
                """<!doctype html><html lang="en"><head>
                <title>Test</title><meta name="description" content="Test page">
                <link rel="canonical" href="https://example.com/">
                </head><body><h1>Test</h1><script>const auth = "Bearer public-token";</script></body></html>""",
                encoding="utf-8",
            )
            (root / "sitemap.xml").write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
                <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                  <url><loc>https://example.com/</loc></url>
                </urlset>""",
                encoding="utf-8",
            )
            config = {
                "canonicalBase": "https://example.com",
                "sitemapPath": "/sitemap.xml",
                "requiredSourceFiles": [],
                "sourceHtmlExcludedFromSitemap": [],
                "prohibitedSourcePatterns": ["Bearer public-token"],
            }

            issues, _ = sitecheck.source_check(root, config)

            matches = [issue for issue in issues if issue.code == "source.prohibited"]
            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0].subject, "index.html")

    def test_source_patterns_include_allowlisted_non_html_text(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "index.html").write_text(
                """<!doctype html><html lang="en"><head>
                <title>Test</title><meta name="description" content="Test page">
                <link rel="canonical" href="https://example.com/">
                </head><body><h1>Test</h1></body></html>""",
                encoding="utf-8",
            )
            (root / "llms.txt").write_text("Authorization: Bearer public-token", encoding="utf-8")
            (root / "sitemap.xml").write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
                <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                  <url><loc>https://example.com/</loc></url>
                </urlset>""",
                encoding="utf-8",
            )
            config = {
                "canonicalBase": "https://example.com",
                "sitemapPath": "/sitemap.xml",
                "requiredSourceFiles": [],
                "sourceHtmlExcludedFromSitemap": [],
                "sourceTextGlobs": ["llms.txt"],
                "prohibitedSourcePatterns": ["Bearer public-token"],
            }

            issues, _ = sitecheck.source_check(root, config)

            matches = [issue for issue in issues if issue.code == "source.prohibited"]
            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0].subject, "llms.txt")


class FailureHandlingTests(unittest.TestCase):
    def test_live_check_enforces_expected_sitemap_count(self) -> None:
        sitemap = b"""<?xml version="1.0" encoding="UTF-8"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://example.com/</loc></url>
        </urlset>"""
        homepage = b"""<!doctype html><html lang="en"><head>
        <title>Home</title><meta name="description" content="Home page">
        <link rel="canonical" href="https://example.com/">
        </head><body><h1>Home</h1></body></html>"""

        def fake_fetch(url: str, follow: bool = True):
            if url.endswith("/sitemap.xml"):
                return 200, {}, sitemap, url
            return 200, {}, homepage, url

        config = {
            "baseUrl": "https://example.com",
            "canonicalBase": "https://example.com",
            "sitemapPath": "/sitemap.xml",
            "expectedSitemapUrlCount": 2,
        }
        with patch.object(sitecheck, "fetch", side_effect=fake_fetch):
            issues, summary = sitecheck.live_check(config, 0)

        self.assertEqual(summary["sitemapUrls"], 1)
        self.assertIn("sitemap.count", {issue.code for issue in issues})

    def test_network_failure_returns_structured_result(self) -> None:
        with patch.object(sitecheck.urllib.request, "build_opener") as build_opener:
            build_opener.return_value.open.side_effect = urllib.error.URLError("offline")
            status, headers, body, final_url = sitecheck.fetch("https://example.invalid/")

        self.assertEqual(status, 0)
        self.assertEqual(body, b"")
        self.assertEqual(final_url, "https://example.invalid/")
        self.assertIn("offline", sitecheck.response_failure(status, headers))


if __name__ == "__main__":
    unittest.main()
