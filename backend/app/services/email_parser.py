from __future__ import annotations

import re
from email import policy
from email.message import EmailMessage as StdEmailMessage
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime, parseaddr
from html import unescape

from bs4 import BeautifulSoup


LINK_RE = re.compile(r"https?://[^\s<>'\")]+", re.IGNORECASE)


def parse_message(raw: bytes) -> StdEmailMessage:
    return BytesParser(policy=policy.default).parsebytes(raw)


def header_text(msg: StdEmailMessage, name: str) -> str:
    value = msg.get(name)
    return str(value) if value else ""


def parse_datetime(value: str):
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except Exception:
        return None


def parse_sender(value: str) -> tuple[str | None, str | None]:
    name, addr = parseaddr(value)
    return name or None, addr or None


def parse_address_list(value: str) -> list[str]:
    return [addr for _, addr in getaddresses([value]) if addr]


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text("\n")
    return normalize_text(unescape(text))


def normalize_text(text: str) -> str:
    lines = [line.strip() for line in text.replace("\r", "\n").split("\n")]
    lines = [line for line in lines if line]
    return "\n".join(lines)


def extract_body(msg: StdEmailMessage) -> tuple[str, str, bool]:
    text_parts: list[str] = []
    html_parts: list[str] = []
    has_attachments = False

    if msg.is_multipart():
        for part in msg.walk():
            content_disposition = part.get_content_disposition()
            content_type = part.get_content_type()
            if content_disposition == "attachment":
                has_attachments = True
                continue
            try:
                content = part.get_content()
            except Exception:
                continue
            if content_type == "text/plain" and isinstance(content, str):
                text_parts.append(content)
            elif content_type == "text/html" and isinstance(content, str):
                html_parts.append(content)
    else:
        content_type = msg.get_content_type()
        try:
            content = msg.get_content()
        except Exception:
            content = ""
        if content_type == "text/html" and isinstance(content, str):
            html_parts.append(content)
        elif isinstance(content, str):
            text_parts.append(content)

    text = normalize_text("\n".join(text_parts))
    html = "\n".join(html_parts)
    clean_text = text or _html_to_text(html)
    return clean_text, html, has_attachments


def extract_links(text: str) -> list[str]:
    seen: set[str] = set()
    links: list[str] = []
    for match in LINK_RE.finditer(text):
        link = match.group(0).rstrip("。.,，)")
        if link not in seen:
            seen.add(link)
            links.append(link)
    return links


def snippet(text: str, length: int = 240) -> str:
    normalized = " ".join(text.split())
    return normalized[:length]
