"""Сохранение ответа в папку «Черновики» по IMAP (Gmail: пароль приложения, без OAuth)."""

from __future__ import annotations

import imaplib
import json
import re
import threading
import time
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from ..config import get_settings

LIST_LINE = re.compile(rb'\((?P<flags>[^)]*)\) (?:"[^"]*"|NIL) (?P<name>.+)$')
_lock = threading.Lock()


class MailboxNotConfigured(RuntimeError):
    pass


def _drafts_folder(imap: imaplib.IMAP4) -> str:
    """Папка с флагом \\Drafts (у Gmail имя локализовано, например «[Gmail]/Черновики»)."""
    _, lines = imap.list()
    for line in lines or []:
        match = LIST_LINE.match(line or b"")
        if match and b"\\drafts" in match["flags"].lower():
            name = match["name"].decode()
            return name if name.startswith('"') else f'"{name}"'
    return "Drafts"


def build_draft(
    to: str, subject: str, text: str, html: str, in_reply_to: str = "", references: str = ""
) -> EmailMessage:
    sender = get_settings().email_own_address
    message = EmailMessage()
    message["From"] = sender
    message["To"] = to
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid(domain=sender.rpartition("@")[2] or None)
    if in_reply_to:
        # Эти заголовки и «Re: тема» кладут черновик в ту же цепочку
        message["In-Reply-To"] = in_reply_to
        message["References"] = f"{references} {in_reply_to}".strip()
    message.set_content(text)
    message.add_alternative(html, subtype="html")
    return message


def save_draft(message: EmailMessage) -> None:
    settings = get_settings()
    password = settings.email_app_password.replace(" ", "")
    if not (settings.email_own_address and password):
        raise MailboxNotConfigured("Укажите EMAIL_OWN_ADDRESS и EMAIL_APP_PASSWORD в .env")
    with imaplib.IMAP4_SSL(settings.email_imap_host, settings.email_imap_port) as imap:
        imap.login(settings.email_own_address, password)
        imap.append(
            _drafts_folder(imap),
            "(\\Draft)",
            imaplib.Time2Internaldate(time.time()),
            message.as_bytes(),
        )


def claim(message_id: str) -> bool:
    """True, если по письму ещё не создавали черновик (защита от повторов при опросе)."""
    if not message_id:
        return True
    path = get_settings().data_dir / "email" / "processed.json"
    with _lock:
        seen = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        if message_id in seen:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(seen[-5000:] + [message_id]), encoding="utf-8")
        return True


def release(message_id: str) -> None:
    """Снять отметку, если сохранить черновик не удалось: письмо обработается повторно."""
    path = get_settings().data_dir / "email" / "processed.json"
    with _lock:
        if message_id and path.exists():
            seen = json.loads(path.read_text(encoding="utf-8"))
            path.write_text(json.dumps([m for m in seen if m != message_id]), encoding="utf-8")
