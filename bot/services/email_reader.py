"""
Чтение писем и поиск кодов (IMAP).
Поддерживает популярные провайдеры по домену.
"""
import re
import imaplib
import email
from email.header import decode_header
from typing import Tuple, Optional, List


# host, port
IMAP_SERVERS = {
    "gmail.com": ("imap.gmail.com", 993),
    "googlemail.com": ("imap.gmail.com", 993),
    "yandex.ru": ("imap.yandex.ru", 993),
    "yandex.com": ("imap.yandex.ru", 993),
    "mail.ru": ("imap.mail.ru", 993),
    "bk.ru": ("imap.mail.ru", 993),
    "inbox.ru": ("imap.mail.ru", 993),
    "list.ru": ("imap.mail.ru", 993),
    "outlook.com": ("outlook.office365.com", 993),
    "hotmail.com": ("outlook.office365.com", 993),
    "live.com": ("outlook.office365.com", 993),
    "rambler.ru": ("imap.rambler.ru", 993),
    "icloud.com": ("imap.mail.me.com", 993),
}


CODE_RE = re.compile(
    r"(?:code|код|otp|password|пароль|verification)[^\d]{0,20}(\d{4,8})"
    r"|(\d{4,8})[^\d]{0,20}(?:code|код|otp)",
    re.I,
)
SIMPLE_CODE_RE = re.compile(r"\b(\d{6})\b")


def _decode_mime(s):
    if not s:
        return ""
    parts = decode_header(s)
    out = []
    for part, enc in parts:
        if isinstance(part, bytes):
            out.append(part.decode(enc or "utf-8", errors="ignore"))
        else:
            out.append(part)
    return "".join(out)


def _get_imap_host(email_addr: str) -> Tuple[str, int]:
    domain = email_addr.split("@")[-1].lower()
    if domain in IMAP_SERVERS:
        return IMAP_SERVERS[domain]
    return f"imap.{domain}", 993


def fetch_latest_codes(email_addr: str, password: str, limit: int = 10) -> Tuple[bool, str, List[str]]:
    """
    Возвращает (ok, message, list_of_codes_or_snippets).
    """
    host, port = _get_imap_host(email_addr)
    try:
        mail = imaplib.IMAP4_SSL(host, port)
        mail.login(email_addr, password)
        mail.select("INBOX")
        status, data = mail.search(None, "ALL")
        if status != "OK":
            mail.logout()
            return False, "Не удалось прочитать INBOX", []

        ids = data[0].split()
        if not ids:
            mail.logout()
            return True, "Почта пустая", []

        codes = []
        snippets = []
        for num in reversed(ids[-limit:]):
            st, msg_data = mail.fetch(num, "(RFC822)")
            if st != "OK":
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            subject = _decode_mime(msg.get("Subject", ""))
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    ctype = part.get_content_type()
                    if ctype == "text/plain":
                        try:
                            body += part.get_payload(decode=True).decode(errors="ignore")
                        except Exception:
                            pass
            else:
                try:
                    body = msg.get_payload(decode=True).decode(errors="ignore")
                except Exception:
                    body = str(msg.get_payload())

            text = f"{subject}\n{body}"
            found = CODE_RE.findall(text)
            for a, b in found:
                c = a or b
                if c and c not in codes:
                    codes.append(c)
            if not found:
                for m in SIMPLE_CODE_RE.findall(text):
                    if m not in codes:
                        codes.append(m)
            snippets.append(f"{subject[:80]}")

        mail.logout()
        if codes:
            return True, "Коды найдены", codes
        return True, "Письма есть, кодов не найдено. Темы: " + "; ".join(snippets[:5]), []
    except imaplib.IMAP4.error as e:
        return False, f"Ошибка входа в почту: {e}", []
    except Exception as e:
        return False, f"Ошибка: {e}", []
