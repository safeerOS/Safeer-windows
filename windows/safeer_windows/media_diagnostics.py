"""Varna obdelava diagnostičnih dogodkov iz medijskega WebView2."""

import json
import urllib.parse


def source_rejection(events_text: str, source_url: str) -> str:
    """Povzame jasne HTTP zavrnitve vira brez poti ali URL žetonov."""
    source_host = (urllib.parse.urlsplit(source_url).hostname or "").casefold()
    for line in reversed(events_text.splitlines()):
        try:
            event = json.loads(line)
        except (ValueError, TypeError):
            continue
        if event.get("type") != "HTTP_ERROR":
            continue
        detail = str(event.get("detail") or "")
        host, _, rest = detail.partition(" status=")
        status_text, _, content_type = rest.partition(" type=")
        try:
            status = int(status_text)
        except ValueError:
            continue
        host = host.casefold()
        is_explicit_rejection = status == 428 or (
            status in (401, 403, 404, 410, 451) and host == source_host
        ) or (status == 403 and content_type.casefold().startswith("text/html"))
        if is_explicit_rejection:
            return f"HTTP {status} · {host or 'vir'}"
    return ""
