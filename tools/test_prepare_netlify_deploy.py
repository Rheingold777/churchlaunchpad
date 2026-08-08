#!/usr/bin/env python3
"""Regression tests for the public-only Netlify package builder."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import prepare_netlify_deploy


class PackageBuilderTests(unittest.TestCase):
    def test_only_allowlisted_public_files_are_copied(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            root = workspace / "repo"
            output = workspace / "public"
            root.mkdir()
            (root / "index.html").write_text("<h1>Home</h1>", encoding="utf-8")
            (root / "styles.css").write_text("body{}", encoding="utf-8")
            (root / "README.md").write_text("internal", encoding="utf-8")
            (root / "tools").mkdir()
            (root / "tools" / "private.py").write_text("secret = True", encoding="utf-8")
            (root / "images").mkdir()
            (root / "images" / "proof.png").write_bytes(b"image")
            config = {
                "propertyKey": "test:site",
                "deployment": {
                    "provider": "netlify",
                    "package": {
                        "rootFiles": ["*.html", "styles.css"],
                        "directories": ["images"],
                    },
                },
            }

            manifest = prepare_netlify_deploy.build_package(root, output, config)

            self.assertEqual(
                [entry["path"] for entry in manifest["files"]],
                ["images/proof.png", "index.html", "styles.css"],
            )
            self.assertFalse((output / "README.md").exists())
            self.assertFalse((output / "tools").exists())

    def test_output_inside_repository_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "index.html").write_text("<h1>Home</h1>", encoding="utf-8")
            config = {
                "deployment": {
                    "provider": "netlify",
                    "package": {"rootFiles": ["*.html"], "directories": []},
                }
            }

            with self.assertRaisesRegex(ValueError, "outside the repository"):
                prepare_netlify_deploy.build_package(root, root / "public", config)

    def test_nested_globs_exclude_unreferenced_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            root = workspace / "repo"
            output = workspace / "public"
            (root / "brand").mkdir(parents=True)
            (root / "images" / "services").mkdir(parents=True)
            (root / "index.html").write_text("<h1>Home</h1>", encoding="utf-8")
            (root / "brand" / "founder.jpg").write_bytes(b"founder")
            (root / "brand" / "unused.png").write_bytes(b"unused")
            (root / "images" / "services" / "local-seo-v2.webp").write_bytes(b"current")
            (root / "images" / "services" / "local-seo.webp").write_bytes(b"old")
            config = {
                "deployment": {
                    "provider": "netlify",
                    "package": {
                        "rootFiles": [
                            "*.html",
                            "brand/founder.jpg",
                            "images/services/*-v2.webp",
                        ],
                        "directories": [],
                    },
                }
            }

            manifest = prepare_netlify_deploy.build_package(root, output, config)

            self.assertEqual(
                [entry["path"] for entry in manifest["files"]],
                [
                    "brand/founder.jpg",
                    "images/services/local-seo-v2.webp",
                    "index.html",
                ],
            )
            self.assertFalse((output / "brand" / "unused.png").exists())
            self.assertFalse((output / "images" / "services" / "local-seo.webp").exists())

    def test_parent_traversal_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "stay relative"):
            prepare_netlify_deploy.safe_relative("../private.txt")


if __name__ == "__main__":
    unittest.main()
