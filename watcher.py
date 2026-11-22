#!/usr/bin/env python3
"""Watch a Markdown internship table and notify Telegram about new roles."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SOURCE_URL = (
    "https://raw.githubusercontent.com/didtheyghostme/"
    "Singapore-Summer2026-TechInternships/main/README.md"
)
STATE_PATH = Path(__file__).parent / "state" / "seen_rows.json"
DEFAULT_KEYWORDS = (
    "software,swe,engineer,developer,backend,full stack,fullstack,data,ai,ml,agent"
)
SEPARATOR_RE = re.compile(r"^:?-{3,}:?$")
MARKDOWN_LINK_RE = re.compile(r"!?\[([^\]]*)\]\((?:[^()]|\([^()]*\))*\)")
HTML_IMAGE_RE = re.compile(
    r"<img\b[^>]*\balt=[\"']([^\"']*)[\"'][^>]*>", re.IGNORECASE
)
HTML_TAG_RE = re.compile(r"<[^>]+>")
HREF_RE = re.compile(r"<a\b[^>]*\bhref=[\"']([^\"']+)[\"']", re.IGNORECASE)
MARKDOWN_URL_RE = re.compile(r"!?\[[^\]]*\]\(([^ )]+)(?:\s+[^)]*)?\)")


@dataclass(frozen=True)
class Row:
    key: str
    company: str
    role: str
    location: str
    application_url: str


def fetch_markdown() -> str:
    request = Request(SOURCE_URL, headers={"User-Agent": "internship-watcher/1.0"})
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def split_row(line: str) -> list[str]:
    """Split a Markdown table row while preserving escaped pipe characters."""
    marker = "\0PIPE\0"
    return [
        cell.replace(marker, "|").strip()
        for cell in line.strip().strip("|").replace(r"\|", marker).split("|")
    ]


def plain_text(value: str) -> str:
    """Remove link/tag formatting and collapse whitespace."""
    value = MARKDOWN_LINK_RE.sub(r"\1", value)
    value = HTML_IMAGE_RE.sub(r"\1", value)
    value = HTML_TAG_RE.sub("", value)
    return " ".join(html.unescape(value).split())


def link_from(value: str) -> str:
    match = HREF_RE.search(value) or MARKDOWN_URL_RE.search(value)
    return html.unescape(match.group(1)) if match else ""


def parse_rows(markdown: str) -> list[Row]:
    headers: list[str] = []
    rows: list[Row] = []

    for line in markdown.splitlines():
        if not line.lstrip().startswith("|"):
            continue

        cells = split_row(line)
        normalized = [plain_text(cell).casefold() for cell in cells]
        if cells and all(SEPARATOR_RE.fullmatch(cell.replace(" ", "")) for cell in cells):
            continue
        if "company" in normalized and "role" in normalized:
            headers = normalized
            continue
        if not headers or len(cells) != len(headers):
            continue

        def cell_named(*names: str) -> str:
            for name in names:
                if name in headers:
                    return cells[headers.index(name)]
            return ""

        company_cell = cell_named("company")
        role_cell = cell_named("role")
        location_cell = cell_named("location")
        application_cell = cell_named("application", "apply", "application link", "link")
        company = plain_text(company_cell)
        role = plain_text(role_cell)
        if not company or not role:
            continue

        # Hash the normalized row after removing link destinations, so tracking
        # parameters and whitespace-only edits do not look like new roles.
        normalized_row = "\x1f".join(plain_text(cell).casefold() for cell in cells)
        rows.append(
            Row(
                key=hashlib.sha256(normalized_row.encode()).hexdigest(),
                company=company,
                role=role,
                location=plain_text(location_cell) or "Not listed",
                application_url=link_from(application_cell),
            )
        )

    # Preserve source order while ignoring accidental duplicate rows.
    return list({row.key: row for row in rows}.values())


def load_seen() -> set[str]:
    if not STATE_PATH.exists():
        return set()
    data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not all(isinstance(item, str) for item in data):
        raise ValueError(f"{STATE_PATH} must contain a JSON array of strings")
    return set(data)


def save_seen(keys: list[str]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(keys, indent=2) + "\n", encoding="utf-8")
    temporary.replace(STATE_PATH)


def matches_keywords(row: Row, keywords: list[str]) -> bool:
    role = row.role.casefold()
    return not keywords or any(keyword in role for keyword in keywords)


def telegram_messages(rows: list[Row]) -> list[str]:
    title = f"New matching internship{'s' if len(rows) != 1 else ''}: {len(rows)}"
    entries = [
        "\n".join(
            (
                f"• {row.company}",
                f"Role: {row.role}",
                f"Location: {row.location}",
                f"Apply: {row.application_url or 'Not listed'}",
            )
        )
        for row in rows
    ]
    messages: list[str] = []
    current = title
    for entry in entries:
        candidate = f"{current}\n\n{entry}"
        if len(candidate) > 4000 and current != title:
            messages.append(current)
            current = f"{title} (continued)\n\n{entry}"
        else:
            current = candidate
    messages.append(current)
    return messages


def notify(rows: list[Row]) -> None:
    """Send alerts through Telegram; replace this function for another service."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        raise ValueError(
            "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required when sending alerts"
        )

    endpoint = f"https://api.telegram.org/bot{token}/sendMessage"
    for message in telegram_messages(rows):
        request = Request(
            endpoint,
            data=urlencode({"chat_id": chat_id, "text": message}).encode(),
            headers={"User-Agent": "internship-watcher/1.0"},
        )
        with urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
        if not result.get("ok"):
            raise RuntimeError(f"Telegram rejected the message: {result}")


def main() -> int:
    try:
        rows = parse_rows(fetch_markdown())
        if not rows:
            raise ValueError("no internship rows were found; refusing to overwrite state")

        seen = load_seen()
        current_keys = [row.key for row in rows]

        # Seed state on the first run without alerting on the existing backlog.
        if not seen:
            save_seen(current_keys)
            print(f"Initialized state with {len(rows)} existing rows; no alert sent.")
            return 0

        keywords = [
            keyword.strip().casefold()
            for keyword in os.environ.get("ROLE_KEYWORDS", DEFAULT_KEYWORDS).split(",")
            if keyword.strip()
        ]
        matched = [
            row
            for row in rows
            if row.key not in seen and matches_keywords(row, keywords)
        ]

        # Keep only current rows, allowing a removed role to alert if re-added later.
        save_seen(current_keys)
        if not matched:
            print("No new matching roles.")
            return 0

        notify(matched)
        print(f"Sent {len(matched)} new matching role(s) to Telegram.")
        return 0
    except (HTTPError, URLError, OSError, UnicodeError, ValueError, RuntimeError) as error:
        print(f"Watcher failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
