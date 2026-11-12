"""Serverseitige Datei-Verarbeitung fuer Anhaenge.

Der Client laedt die Rohdatei hoch (Multipart-Form); hier wird entschieden,
ob es sich um eine Textdatei handelt, sie als UTF-8 dekodiert (mit explizitem
Kuerzungs-Marker jenseits des Limits) bzw. als Data-URL (Bilder) aufbereitet.
Beim LLM-Request werden Anhang-Referenzen (``attachment_id`` in Content-Parts)
in die verarbeiteten Content-Parts expandiert.
"""

from __future__ import annotations

import base64
from typing import Any

MAX_TEXT_CHARS = 100_000
MAX_UPLOAD_BYTES = 20 * 1024 * 1024

TEXT_MIME_TYPES = {
    "application/json",
    "application/xml",
    "application/javascript",
    "application/x-yaml",
    "application/yaml",
}
TEXT_EXTENSIONS = {
    "txt", "md", "markdown", "json", "csv", "tsv", "log", "xml", "yaml", "yml",
    "py", "js", "mjs", "cjs", "ts", "html", "htm", "css", "ini", "cfg", "conf",
    "env", "c", "h", "cpp", "java", "go", "rs", "sh", "sql", "toml",
}


def is_text_file(name: str, mime: str) -> bool:
    t = (mime or "").lower()
    if t.startswith("image/"):
        return False
    if t.startswith("text/"):
        return True
    if t in TEXT_MIME_TYPES or t.endswith("+json") or t.endswith("+xml"):
        return True
    if not t and "." in name:
        return name.rsplit(".", 1)[1].lower() in TEXT_EXTENSIONS
    return False


def process_upload(name: str, mime: str, raw: bytes) -> dict:
    """Bereitet eine hochgeladene Datei fuer die Speicherung und den LLM-Request auf."""
    mime = (mime or "").lower() or "application/octet-stream"
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError(f"Datei zu gross ({len(raw)} Bytes, Limit {MAX_UPLOAD_BYTES})")
    if mime.startswith("image/"):
        data_url = "data:%s;base64,%s" % (mime, base64.b64encode(raw).decode("ascii"))
        return {"name": name, "mime": mime, "kind": "image", "size": len(raw), "content": data_url}
    if is_text_file(name, mime):
        text = raw.decode("utf-8", errors="replace")
        if len(text) > MAX_TEXT_CHARS:
            text = text[:MAX_TEXT_CHARS] + "\n[… gekürzt: Datei zu lang für Inline-Übertragung]"
        return {"name": name, "mime": mime, "kind": "text", "size": len(raw), "content": text}
    return {
        "name": name,
        "mime": mime,
        "kind": "binary",
        "size": len(raw),
        "content": f"(Binärdatei, {len(raw)} Bytes – wird nicht als Text übertragen)",
    }


def _attachment_part(att: dict) -> dict:
    if att["kind"] == "image":
        return {"type": "image_url", "image_url": {"url": att["content"]}}
    return {"type": "text", "text": f"[Datei: {att['name']}]\n{att['content']}"}


def expand_attachment_parts(messages: list[dict[str, Any]], attachments_by_id: dict[int, dict]) -> list[dict[str, Any]]:
    """Ersetzt Content-Parts mit ``attachment_id`` durch die serverseitig aufbereiteten Parts.

    Rein textuelle Content-Listen werden zu einem einzigen String verschmolzen:
    manche LLM-Server verlangen ``content`` als String und antworten sonst mit
    HTTP 422. Nur bei Bild-Parts bleibt die Listenform (image_url) erhalten.
    """
    for m in messages:
        content = m.get("content")
        if not isinstance(content, list):
            continue
        expanded = []
        for part in content:
            aid = part.get("attachment_id") if isinstance(part, dict) else None
            if aid is not None and int(aid) in attachments_by_id:
                expanded.append(_attachment_part(attachments_by_id[int(aid)]))
            else:
                expanded.append(part)
        if expanded and all(isinstance(p, dict) and p.get("type") == "text" for p in expanded):
            m["content"] = "\n\n".join(str(p["text"]) for p in expanded)
        else:
            m["content"] = expanded
    return messages
