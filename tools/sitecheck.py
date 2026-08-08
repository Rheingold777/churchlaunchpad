#!/usr/bin/env python3
"""Dependency-free source and production contract checks for managed websites."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any


USER_AGENT = "ManagedWebsiteOps/1.1 (+https://rheingolddigital.com/)"
FETCH_ERROR_HEADER = "X-Website-Ops-Fetch-Error"


@dataclass
class Issue:
    severity: str
    code: str
    subject: str
    message: str


@dataclass
class Page:
    subject: str
    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    title: str = ""
    title_count: int = 0
    description: str = ""
    h1: list[str] = field(default_factory=list)
    headings: list[int] = field(default_factory=list)
    canonical: list[str] = field(default_factory=list)
    robots: str = ""
    lang: str = ""
    links: set[str] = field(default_factory=set)
    assets: set[str] = field(default_factory=set)
    missing_alt: list[str] = field(default_factory=list)
    jsonld_errors: list[str] = field(default_factory=list)
    forms: list[dict[str, Any]] = field(default_factory=list)
    text: str = ""


class Inspector(HTMLParser):
    def __init__(self, subject: str):
        super().__init__(convert_charrefs=True)
        self.page = Page(subject=subject)
        self._title = False
        self._title_parts: list[str] = []
        self._heading: int | None = None
        self._heading_parts: list[str] = []
        self._script_jsonld = False
        self._script_parts: list[str] = []
        self._skip_text = 0
        self._text_parts: list[str] = []
        self._form: dict[str, Any] | None = None

    @staticmethod
    def _attrs(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {key.lower(): (value or "") for key, value in attrs}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        data = self._attrs(attrs)
        if tag == "img" and "alt" not in data:
            self.page.missing_alt.append(data.get("src", "(inline image)"))
        if tag == "html":
            self.page.lang = data.get("lang", "")
        elif tag == "title":
            self._title = True
            self._title_parts = []
            self.page.title_count += 1
        elif re.fullmatch(r"h[1-6]", tag):
            self._heading = int(tag[1])
            self._heading_parts = []
            self.page.headings.append(self._heading)
        elif tag == "meta":
            name = data.get("name", "").lower()
            if name == "description":
                self.page.description = data.get("content", "").strip()
            elif name == "robots":
                self.page.robots = data.get("content", "").lower()
        elif tag == "link":
            rel = set(data.get("rel", "").lower().split())
            if "canonical" in rel and data.get("href"):
                self.page.canonical.append(data["href"].strip())
            if rel.intersection({"stylesheet", "icon", "preload"}) and data.get("href"):
                self.page.assets.add(data["href"].strip())
        elif tag == "a" and data.get("href"):
            self.page.links.add(data["href"].strip())
        elif tag in {"img", "script"} and data.get("src"):
            self.page.assets.add(data["src"].strip())
        if tag == "script":
            self._skip_text += 1
            if data.get("type", "").lower() == "application/ld+json":
                self._script_jsonld = True
                self._script_parts = []
        elif tag == "style":
            self._skip_text += 1

        if tag == "form":
            self._form = {
                "name": data.get("name", ""),
                "method": data.get("method", "get").lower(),
                "action": data.get("action", ""),
                "netlify": "data-netlify" in data or "netlify" in data,
                "fields": {},
            }
        elif self._form is not None and tag in {"input", "textarea", "select"}:
            name = data.get("name", "")
            if name:
                input_type = tag if tag != "input" else data.get("type", "text").lower()
                self._form["fields"][name] = {
                    "type": input_type,
                    "required": "required" in data,
                }

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title" and self._title:
            self.page.title = " ".join("".join(self._title_parts).split())
            self._title = False
        elif self._heading is not None and tag == f"h{self._heading}":
            value = " ".join("".join(self._heading_parts).split())
            if self._heading == 1:
                self.page.h1.append(value)
            self._heading = None
        elif tag == "script":
            if self._script_jsonld:
                raw = "".join(self._script_parts).strip()
                try:
                    json.loads(raw)
                except json.JSONDecodeError as exc:
                    self.page.jsonld_errors.append(f"line {exc.lineno}, column {exc.colno}: {exc.msg}")
                self._script_jsonld = False
            self._skip_text = max(0, self._skip_text - 1)
        elif tag == "style":
            self._skip_text = max(0, self._skip_text - 1)
        elif tag == "form" and self._form is not None:
            self.page.forms.append(self._form)
            self._form = None

    def handle_data(self, data: str) -> None:
        if self._title:
            self._title_parts.append(data)
        if self._heading is not None:
            self._heading_parts.append(data)
        if self._script_jsonld:
            self._script_parts.append(data)
        if self._skip_text == 0 and data.strip():
            self._text_parts.append(data.strip())

    def finish(self) -> Page:
        self.page.text = " ".join(" ".join(self._text_parts).split())
        return self.page


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def parse_html(subject: str, raw: bytes, headers: dict[str, str] | None = None, status: int = 200) -> Page:
    parser = Inspector(subject)
    parser.feed(raw.decode("utf-8", errors="replace"))
    page = parser.finish()
    page.status = status
    page.headers = {key.lower(): value for key, value in (headers or {}).items()}
    return page


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    if not isinstance(config, dict):
        raise ValueError("configuration root must be a JSON object")
    for required in ("schemaVersion", "propertyKey", "baseUrl", "canonicalBase", "sitemapPath"):
        if not isinstance(config.get(required), str) or not config[required].strip():
            raise ValueError(f"configuration is missing non-empty string: {required}")
    for key in ("baseUrl", "canonicalBase"):
        parsed = urllib.parse.urlsplit(config[key])
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"configuration value {key} must be an absolute HTTP(S) URL")
    if not config["sitemapPath"].startswith("/"):
        raise ValueError("configuration value sitemapPath must begin with /")
    source_root = config.get("sourceRoot", ".")
    if not isinstance(source_root, str) or not source_root.strip():
        raise ValueError("configuration value sourceRoot must be a non-empty string")
    source_root_path = PurePosixPath(source_root.replace("\\", "/"))
    if source_root_path.is_absolute() or ".." in source_root_path.parts:
        raise ValueError("configuration value sourceRoot must stay relative to the repository")
    virtual_paths = config.get("sourceVirtualSitemapPaths", [])
    if not isinstance(virtual_paths, list) or any(
        not isinstance(item, str) or not item.startswith("/") for item in virtual_paths
    ):
        raise ValueError("configuration value sourceVirtualSitemapPaths must contain absolute URL paths")
    expected_sitemap_count = config.get("expectedSitemapUrlCount")
    if expected_sitemap_count is not None and (
        not isinstance(expected_sitemap_count, int) or isinstance(expected_sitemap_count, bool) or expected_sitemap_count < 0
    ):
        raise ValueError("configuration value expectedSitemapUrlCount must be a non-negative integer or null")
    return config


def add(issues: list[Issue], severity: str, code: str, subject: str, message: str) -> None:
    issues.append(Issue(severity, code, subject, message))


def canonical_for(base: str, path: str) -> str:
    return base.rstrip("/") + ("/" if path == "/" else path)


def path_for_html(
    filename: str,
    directory_index_trailing_slash: bool = False,
    keep_html_extension: bool = False,
) -> str:
    relative = PurePosixPath(filename.replace("\\", "/"))
    if relative.name == "index.html":
        parent = relative.parent.as_posix()
        if parent == ".":
            return "/"
        suffix = "/" if directory_index_trailing_slash else ""
        return "/" + parent.strip("/") + suffix
    public_path = relative if keep_html_extension else relative.with_suffix("")
    return "/" + public_path.as_posix().lstrip("/")


def source_html_files(root: Path, config: dict[str, Any]) -> list[tuple[str, Path]]:
    """Return the explicitly allowlisted source HTML files, de-duplicated by relative path."""
    files: dict[str, Path] = {}
    for pattern in config.get("sourceHtmlGlobs", ["*.html"]):
        for item in root.glob(pattern):
            if item.is_file():
                relative = item.relative_to(root).as_posix()
                files[relative] = item
    return [(relative, files[relative]) for relative in sorted(files)]


def source_text_files(root: Path, config: dict[str, Any]) -> list[tuple[str, Path]]:
    """Return additional explicitly allowlisted text files for source-pattern checks."""
    files: dict[str, Path] = {}
    for pattern in config.get("sourceTextGlobs", []):
        for item in root.glob(pattern):
            if item.is_file():
                relative = item.relative_to(root).as_posix()
                files[relative] = item
    return [(relative, files[relative]) for relative in sorted(files)]


def inspect_core(page: Page, path: str, config: dict[str, Any], issues: list[Issue], indexable: bool = True) -> None:
    if page.title_count != 1 or not page.title:
        add(issues, "error", "html.title", page.subject, f"expected one non-empty title, found {page.title_count}")
    if not page.description:
        add(issues, "error", "html.description", page.subject, "missing meta description")
    if len(page.h1) != 1 or not page.h1[0]:
        add(issues, "error", "html.h1", page.subject, f"expected one non-empty H1, found {len(page.h1)}")
    if page.lang.lower() != "en":
        add(issues, "error", "html.lang", page.subject, f"expected lang=en, found {page.lang or '(missing)'}")
    if page.missing_alt:
        add(issues, "error", "image.alt", page.subject, "images missing alt: " + ", ".join(page.missing_alt[:5]))
    for error in page.jsonld_errors:
        add(issues, "error", "schema.json", page.subject, error)
    asset_paths = {urllib.parse.urlsplit(asset).path for asset in page.assets}
    for required_asset in config.get("requiredHtmlAssets", []):
        if required_asset not in asset_paths:
            add(issues, "error", "html.asset", page.subject, f"missing required asset {required_asset}")
    link_paths = {urllib.parse.urlsplit(link).path for link in page.links}
    for required_link in config.get("requiredLinksByPath", {}).get(path, []):
        if required_link not in link_paths:
            add(issues, "error", "html.link", page.subject, f"missing required link {required_link}")
    for previous, current in zip(page.headings, page.headings[1:]):
        if current > previous + 1:
            add(issues, "warning", "heading.order", page.subject, f"heading level jumps from H{previous} to H{current}")
            break

    if indexable:
        expected = canonical_for(config["canonicalBase"], path)
        if page.canonical != [expected]:
            add(issues, "error", "seo.canonical", page.subject, f"expected [{expected}], found {page.canonical}")
        if "noindex" in page.robots:
            add(issues, "error", "seo.indexability", page.subject, "indexable page contains noindex")
    elif path in config.get("noindexPaths", []) and "noindex" not in page.robots:
        add(issues, "error", "seo.noindex", page.subject, "required noindex is missing")

    searchable = (page.text + " " + page.title + " " + page.description).casefold()
    for pattern in config.get("prohibitedPublicPatterns", []):
        if pattern.casefold() in searchable:
            add(issues, "error", "copy.prohibited", page.subject, f"contains prohibited pattern: {pattern}")


def inspect_source_patterns(subject: str, source: str, config: dict[str, Any], issues: list[Issue]) -> None:
    """Reject configured source-only literals, including strings hidden inside scripts."""
    searchable = source.casefold()
    for pattern in config.get("prohibitedSourcePatterns", []):
        if pattern.casefold() in searchable:
            add(issues, "error", "source.prohibited", subject, f"contains prohibited source pattern: {pattern}")


def check_form(page: Page, expected: dict[str, Any], issues: list[Issue]) -> None:
    matches = [form for form in page.forms if form.get("name") == expected["name"]]
    if len(matches) != 1:
        add(issues, "error", "form.count", page.subject, f"expected one form named {expected['name']}, found {len(matches)}")
        return
    form = matches[0]
    for key in ("method", "action"):
        if form.get(key) != expected[key]:
            add(issues, "error", f"form.{key}", page.subject, f"expected {key}={expected[key]}, found {form.get(key)}")
    if expected.get("netlify") and not form.get("netlify"):
        add(issues, "error", "form.netlify", page.subject, "source form is missing data-netlify/netlify attribute")
    for name, contract in expected.get("fields", {}).items():
        actual = form["fields"].get(name)
        if actual is None:
            add(issues, "error", "form.field", page.subject, f"missing field {name}")
        elif actual != contract:
            add(issues, "error", "form.field", page.subject, f"field {name}: expected {contract}, found {actual}")


def local_target(root: Path, raw_url: str, canonical_host: str) -> Path | None:
    parsed = urllib.parse.urlsplit(raw_url)
    if parsed.scheme in {"mailto", "tel", "sms", "javascript", "data"}:
        return None
    if parsed.netloc and parsed.netloc.lower() != canonical_host.lower():
        return None
    path = urllib.parse.unquote(parsed.path or "/")
    if path == "/":
        return root / "index.html"
    candidate = root / path.lstrip("/")
    if candidate.suffix:
        return candidate
    flat_html = candidate.with_suffix(".html")
    directory_index = candidate / "index.html"
    if flat_html.is_file():
        return flat_html
    if directory_index.is_file():
        return directory_index
    return flat_html


def source_check(root: Path, config: dict[str, Any]) -> tuple[list[Issue], dict[str, Any]]:
    issues: list[Issue] = []
    source_root = (root / config.get("sourceRoot", ".")).resolve()
    try:
        source_root.relative_to(root)
    except ValueError:
        add(issues, "error", "source.root", str(source_root), "source root escapes the repository")
        return issues, {"mode": "source", "htmlPages": 0, "sitemapUrls": 0, "virtualSitemapUrls": 0}
    if not source_root.is_dir():
        add(issues, "error", "source.root", str(source_root), "source root is missing")
        return issues, {"mode": "source", "htmlPages": 0, "sitemapUrls": 0, "virtualSitemapUrls": 0}
    for filename in config.get("requiredSourceFiles", []):
        if not (root / filename).is_file():
            add(issues, "error", "source.required", filename, "required source file is missing")

    try:
        tree = ET.parse(source_root / config["sitemapPath"].lstrip("/"))
        sitemap_urls = [node.text.strip() for node in tree.findall("{*}url/{*}loc") if node.text]
    except (OSError, ET.ParseError) as exc:
        sitemap_urls = []
        add(issues, "error", "sitemap.parse", config["sitemapPath"], str(exc))

    if len(sitemap_urls) != len(set(sitemap_urls)):
        add(issues, "error", "sitemap.duplicate", "sitemap.xml", "contains duplicate URL entries")

    canonical_host = urllib.parse.urlsplit(config["canonicalBase"]).netloc
    pages: dict[str, Page] = {}
    excluded = set(config.get("sourceHtmlExcludedFromSitemap", []))
    html_files = source_html_files(source_root, config)
    directory_index_trailing_slash = bool(config.get("sourceDirectoryIndexTrailingSlash", False))
    keep_html_extension = bool(config.get("sourceHtmlKeepExtension", False))
    pattern_checked_files: set[str] = set()
    for relative, html_file in html_files:
        path = path_for_html(relative, directory_index_trailing_slash, keep_html_extension)
        raw = html_file.read_bytes()
        inspect_source_patterns(relative, raw.decode("utf-8", errors="replace"), config, issues)
        pattern_checked_files.add(relative)
        page = parse_html(relative, raw)
        if path in pages:
            add(issues, "error", "source.route_duplicate", relative, f"route {path} is also provided by {pages[path].subject}")
        pages[path] = page
        indexable = relative not in excluded
        inspect_core(page, path, config, issues, indexable=indexable)
        if indexable:
            expected_url = canonical_for(config["canonicalBase"], path)
            if expected_url not in sitemap_urls:
                add(issues, "error", "sitemap.missing", relative, f"missing {expected_url}")

    for relative, text_file in source_text_files(source_root, config):
        if relative in pattern_checked_files:
            continue
        inspect_source_patterns(relative, text_file.read_text(encoding="utf-8", errors="replace"), config, issues)

    virtual_paths = set(config.get("sourceVirtualSitemapPaths", []))
    virtual_urls = {canonical_for(config["canonicalBase"], path) for path in virtual_paths}
    expected_indexable = len([relative for relative, _ in html_files if relative not in excluded]) + len(virtual_urls)
    if len(sitemap_urls) != expected_indexable:
        add(issues, "error", "sitemap.count", "sitemap.xml", f"expected {expected_indexable} URLs, found {len(sitemap_urls)}")
    expected_urls = {
        canonical_for(
            config["canonicalBase"],
            path_for_html(relative, directory_index_trailing_slash, keep_html_extension),
        )
        for relative, _ in html_files
        if relative not in excluded
    }
    expected_urls.update(virtual_urls)
    for unexpected in sorted(set(sitemap_urls) - expected_urls):
        add(issues, "error", "sitemap.unexpected", "sitemap.xml", f"unexpected URL {unexpected}")

    for path, page in pages.items():
        for raw_url in page.links | page.assets:
            referenced_path = urllib.parse.urlsplit(raw_url).path or "/"
            if referenced_path in virtual_paths:
                continue
            target = local_target(source_root, raw_url, canonical_host)
            if target is not None and not target.is_file():
                add(issues, "error", "source.reference", page.subject, f"missing local target for {raw_url}: {target.name}")

    form_config = config.get("expectedForm")
    if form_config:
        page = pages.get(form_config["path"])
        if page is None:
            add(issues, "error", "form.page", form_config["path"], "form page is missing")
        else:
            check_form(page, form_config, issues)

    redirects_text = (
        (source_root / "_redirects").read_text(encoding="utf-8") if (source_root / "_redirects").is_file() else ""
    )
    for redirect in config.get("redirectChecks", []):
        pattern = re.compile(rf"(?m)^\s*{re.escape(redirect['from'])}\s+{re.escape(redirect['to'])}\s+{redirect['status']}!\s*$")
        if not pattern.search(redirects_text):
            add(issues, "error", "redirect.source", redirect["from"], "expected forced redirect rule is missing")

    return issues, {
        "mode": "source",
        "htmlPages": len(html_files),
        "sitemapUrls": len(sitemap_urls),
        "virtualSitemapUrls": len(virtual_urls),
        "sourceRoot": source_root.relative_to(root).as_posix() or ".",
    }


def fetch(url: str, follow: bool = True) -> tuple[int, dict[str, str], bytes, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"})
    opener = urllib.request.build_opener() if follow else urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(request, timeout=20) as response:
            return response.status, dict(response.headers.items()), response.read(), response.geturl()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers.items()), exc.read(), exc.geturl()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return 0, {FETCH_ERROR_HEADER: f"{type(exc).__name__}: {exc}"}, b"", url


def response_failure(status: int, headers: dict[str, str]) -> str:
    detail = headers.get(FETCH_ERROR_HEADER, headers.get(FETCH_ERROR_HEADER.lower(), ""))
    return detail or f"returned {status}"


def check_expected_headers(page: Page, config: dict[str, Any], issues: list[Issue]) -> None:
    for name, expected in config.get("expectedHeaders", {}).items():
        actual = page.headers.get(name.lower(), "")
        if actual.lower() != expected.lower():
            add(issues, "error", "http.header", page.subject, f"{name}: expected {expected}, found {actual or '(missing)'}")


def live_check(config: dict[str, Any], delay_ms: int) -> tuple[list[Issue], dict[str, Any]]:
    issues: list[Issue] = []
    base = config.get("baseUrl", config["canonicalBase"]).rstrip("/")
    sitemap_status, sitemap_headers, sitemap_raw, _ = fetch(base + config["sitemapPath"])
    sitemap_urls: list[str] = []
    if sitemap_status != 200:
        add(issues, "error", "sitemap.http", config["sitemapPath"], response_failure(sitemap_status, sitemap_headers))
    else:
        try:
            root = ET.fromstring(sitemap_raw)
            sitemap_urls = [node.text.strip() for node in root.findall("{*}url/{*}loc") if node.text]
        except ET.ParseError as exc:
            add(issues, "error", "sitemap.parse", config["sitemapPath"], str(exc))

    if len(sitemap_urls) != len(set(sitemap_urls)):
        add(issues, "error", "sitemap.duplicate", config["sitemapPath"], "contains duplicate URL entries")
    expected_sitemap_count = config.get("expectedSitemapUrlCount")
    if expected_sitemap_count is not None and len(sitemap_urls) != expected_sitemap_count:
        add(
            issues,
            "error",
            "sitemap.count",
            config["sitemapPath"],
            f"expected {expected_sitemap_count} URLs, found {len(sitemap_urls)}",
        )

    canonical_base = config["canonicalBase"].rstrip("/")
    for url in sitemap_urls:
        parsed = urllib.parse.urlsplit(url)
        path = parsed.path or "/"
        expected = canonical_for(canonical_base, path)
        if parsed.query or parsed.fragment or url.rstrip("/") != expected.rstrip("/"):
            add(issues, "error", "sitemap.canonical", config["sitemapPath"], f"expected canonical URL {expected}, found {url}")

    paths = {urllib.parse.urlsplit(url).path or "/" for url in sitemap_urls}
    paths.update(path for path in config.get("requiredPaths", []) if path.endswith("/") or "." not in Path(path).name)
    pages: dict[str, Page] = {}
    for path in sorted(paths):
        time.sleep(delay_ms / 1000)
        status, headers, raw, final_url = fetch(base + path)
        if status != 200:
            add(issues, "error", "http.status", path, response_failure(status, headers))
            continue
        page = parse_html(path, raw, headers, status)
        pages[path] = page
        indexable = path not in config.get("noindexPaths", [])
        inspect_core(page, path, config, issues, indexable=indexable)
        check_expected_headers(page, config, issues)
        expected_final = base + ("/" if path == "/" else path)
        if final_url.rstrip("/") != expected_final.rstrip("/"):
            add(issues, "warning", "http.final_url", path, f"resolved to {final_url}")

    for required in config.get("requiredPaths", []):
        status, headers, _, _ = fetch(base + required)
        if status != 200:
            add(issues, "error", "http.required", required, response_failure(status, headers))

    form_config = config.get("expectedForm")
    if form_config:
        page = pages.get(form_config["path"])
        if page is None:
            add(issues, "error", "form.page", form_config["path"], "form page unavailable")
        else:
            # Netlify strips its detection attribute after deploy, so only the field/action contract is checked live.
            expected_live = dict(form_config)
            check_form_live(page, expected_live, issues)

    for redirect in config.get("redirectChecks", []):
        status, headers, _, _ = fetch(base + redirect["from"], follow=False)
        location = headers.get("Location", headers.get("location", ""))
        expected_location = base + ("/" if redirect["to"] == "/" else redirect["to"])
        absolute_location = urllib.parse.urljoin(base + redirect["from"], location)
        if status != redirect["status"] or absolute_location.rstrip("/") != expected_location.rstrip("/"):
            add(issues, "error", "redirect.live", redirect["from"], f"expected {redirect['status']} to {expected_location}, found {status} to {location or '(none)'}")

    not_found = config.get("notFoundCheck")
    if not_found:
        status, _, raw, _ = fetch(base + not_found["path"])
        text = raw.decode("utf-8", errors="replace")
        if status != not_found["status"] or not_found["contains"] not in text:
            add(issues, "error", "http.404", not_found["path"], f"expected {not_found['status']} with branded marker")

    return issues, {"mode": "live", "htmlPages": len(pages), "sitemapUrls": len(sitemap_urls), "baseUrl": base}


def check_form_live(page: Page, expected: dict[str, Any], issues: list[Issue]) -> None:
    matches = [form for form in page.forms if form.get("name") == expected["name"]]
    if len(matches) != 1:
        add(issues, "error", "form.count", page.subject, f"expected one form named {expected['name']}, found {len(matches)}")
        return
    form = matches[0]
    for key in ("method", "action"):
        if form.get(key) != expected[key]:
            add(issues, "error", f"form.{key}", page.subject, f"expected {key}={expected[key]}, found {form.get(key)}")
    for name, contract in expected.get("fields", {}).items():
        actual = form["fields"].get(name)
        if actual is None:
            add(issues, "error", "form.field", page.subject, f"missing field {name}")
        elif actual != contract:
            add(issues, "error", "form.field", page.subject, f"field {name}: expected {contract}, found {actual}")


def write_report(path: Path, summary: dict[str, Any], issues: list[Issue]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"summary": summary, "issues": [issue.__dict__ for issue in issues]}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("source", "live"))
    parser.add_argument("--config", type=Path, default=Path("website-ops.json"))
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--base-url", help="override config baseUrl for a local or staging check")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--delay-ms", type=int, default=100)
    args = parser.parse_args()

    try:
        config = load_config(args.config)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        issues = [Issue("error", "config.invalid", str(args.config), str(exc))]
        summary = {"mode": args.mode, "errors": 1, "warnings": 0, "result": "fail"}
        print(json.dumps(summary, indent=2))
        print(f"ERROR   config.invalid       {args.config}: {exc}")
        if args.report:
            write_report(args.report, summary, issues)
        return 1
    if args.base_url:
        config = dict(config)
        config["baseUrl"] = args.base_url.rstrip("/")
    if args.mode == "source":
        issues, summary = source_check(args.root.resolve(), config)
    else:
        issues, summary = live_check(config, max(0, args.delay_ms))

    errors = [issue for issue in issues if issue.severity == "error"]
    warnings = [issue for issue in issues if issue.severity == "warning"]
    summary.update({"errors": len(errors), "warnings": len(warnings), "result": "pass" if not errors else "fail"})

    print(json.dumps(summary, indent=2))
    for issue in issues:
        print(f"{issue.severity.upper():7} {issue.code:20} {issue.subject}: {issue.message}")
    if args.report:
        write_report(args.report, summary, issues)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
