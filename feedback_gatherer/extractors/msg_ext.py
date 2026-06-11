"""Extract Outlook .msg e-mails in two shapes:
  1. MS Form notification - the confirmation e-mail whose body lists the submitted
     feedback as "- <Section label>: <text>" lines. Parsed into per-section items.
  2. Cover mail           - a letter that carries the real response as an attachment.
     The attachments are handed back to the engine to extract recursively; the letter
     body becomes a single low-value "general" cover note.
"""
from __future__ import annotations

import io
import re

import extract_msg

from .base import ParsedSource, RawItem

EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")
# a line like "- Goal of Commercial Conditions: References to ..."
_BULLET_RE = re.compile(r"^\s*[-•]\s*([^:\n]{3,70}):\s*(.*)$")
_DOC_EXT = (".docx", ".pdf", ".xlsx", ".doc")


def _company_from_sender(sender: str) -> str | None:
    """'Carek Sebastian SBB CFF FFS <x@sbb.ch>' -> 'Carek Sebastian SBB CFF FFS'."""
    if not sender:
        return None
    return re.sub(r"<[^>]*>", "", sender).strip().strip('"') or None


def extract(data: bytes, filename: str, cfg: dict) -> list[ParsedSource]:
    msg = extract_msg.Message(io.BytesIO(data))
    body = msg.body or ""
    sender = msg.sender or ""
    subject = msg.subject or ""
    date = _iso(str(msg.date) if msg.date else "")
    attachments = []
    for a in msg.attachments:
        name = a.longFilename or a.shortFilename or ""
        if name.lower().endswith(_DOC_EXT):
            content = a.data
            if isinstance(content, bytes):
                attachments.append((name, content))
    msg.close()

    ps = ParsedSource(source_format="msg", full_text=body, date_hint=date)
    ps.email_hint = (EMAIL_RE.search(sender) or EMAIL_RE.search(body))
    ps.email_hint = ps.email_hint.group(0) if ps.email_hint else None
    ps.company_hint = _company_from_sender(sender)
    ps.attachments = attachments

    # ---- (1) MS Form notification: parse "- Label: text" bullets ----------
    bullets = _parse_bullets(body)
    if bullets and ("submitting" in body.lower() or len(bullets) >= 3):
        # The notification is sent BY the form system (e.g. "RNE Mailbox"), so the
        # sender identifies the transport, not the respondent. Clear those hints -
        # otherwise the first minted respondent's mailbox address would
        # email-match every later notification to the same (wrong) company.
        # Identity must come from the filename or the body instead.
        ps.company_hint = None
        ps.email_hint = None
        for label, text in bullets:
            if text.strip():
                ps.items.append(RawItem(section_raw=label.strip(), considerations=text.strip(),
                                        raw_text=f"- {label.strip()}: {text.strip()}"))
        ps.notes.append("MS Form confirmation e-mail (section-keyed body); "
                        "respondent identified from the filename.")
        return [ps]

    # ---- (2) cover mail ---------------------------------------------------
    if attachments:
        ps.notes.append(f"Cover e-mail; real feedback in attachment(s): "
                        f"{', '.join(n for n, _ in attachments)}.")
    note = body.strip()
    if note:
        ps.items.append(RawItem(section_raw="general", considerations=note, raw_text=note,
                                confidence="low"))
    if not ps.items and not attachments:
        ps.notes.append("Empty e-mail with no attachments.")
    return [ps]


def _parse_bullets(body: str) -> list[tuple[str, str]]:
    """Collect '- Label: text' blocks, joining wrapped continuation lines."""
    out: list[tuple[str, str]] = []
    current_label = None
    current_text: list[str] = []
    for line in body.splitlines():
        m = _BULLET_RE.match(line)
        if m:
            if current_label is not None:
                out.append((current_label, " ".join(current_text).strip()))
            current_label, current_text = m.group(1), [m.group(2)]
        elif current_label is not None:
            if line.strip():
                current_text.append(line.strip())
    if current_label is not None:
        out.append((current_label, " ".join(current_text).strip()))
    return out


def _iso(s: str) -> str | None:
    m = re.search(r"\d{4}-\d{2}-\d{2}", s or "")
    return m.group(0) if m else None
