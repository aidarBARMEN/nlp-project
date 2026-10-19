"""Настроить n8n одной командой: IMAP-доступ из .env, импорт и включение воркфлоу деканата.

Нужно только заполнить в .env EMAIL_OWN_ADDRESS и EMAIL_APP_PASSWORD
(Gmail: https://myaccount.google.com/apppasswords) и запустить:
    .venv\\Scripts\\python.exe scripts\\setup_n8n.py
"""

import imaplib
import json
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from dotenv import set_key

from backend.app.config import Settings
from ingestion.config import PROJECT_DIR

WORKFLOW_ID = "kbtuDeanDrafts01"
CREDENTIAL = {"id": "kbtuDeanImap0001", "name": "Почта деканата (IMAP)", "type": "imap"}


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        args, cwd=PROJECT_DIR, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if check and result.returncode:
        sys.exit(f"Ошибка: {' '.join(args)}\n{result.stdout}{result.stderr}")
    return result


def n8n(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return run("docker", "compose", "exec", "-T", "n8n", "n8n", *args, check=check)


def main() -> None:
    settings = Settings()
    address, password = settings.email_own_address, settings.email_app_password.replace(" ", "")
    if not (address and password):
        sys.exit("Заполните в .env EMAIL_OWN_ADDRESS и EMAIL_APP_PASSWORD и повторите.")

    print(f"Проверка входа в {settings.email_imap_host} как {address}...")
    try:
        with imaplib.IMAP4_SSL(settings.email_imap_host, settings.email_imap_port) as imap:
            imap.login(address, password)
    except imaplib.IMAP4.error as e:
        sys.exit(f"IMAP не пустил: {e}. Нужен пароль приложения, а не обычный пароль Gmail.")

    if not settings.email_start_after:
        # отвечать только на письма, пришедшие после включения, а не на весь старый ящик
        start = datetime.now().astimezone().isoformat(timespec="seconds")
        set_key(PROJECT_DIR / ".env", "EMAIL_START_AFTER", start, quote_mode="never")
        print(f"EMAIL_START_AFTER={start}: более ранние письма обрабатываться не будут.")

    run("docker", "compose", "up", "-d", "n8n")
    credential = {
        **CREDENTIAL,
        "data": {
            "user": address,
            "password": password,
            "host": settings.email_imap_host,
            "port": settings.email_imap_port,
            "secure": True,
            "allowUnauthorizedCerts": False,
        },
    }
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "credentials.json"
        path.write_text(json.dumps([credential], ensure_ascii=False), encoding="utf-8")
        run("docker", "compose", "cp", str(path), "n8n:/tmp/credentials.json")
    try:
        n8n("import:credentials", "--input=/tmp/credentials.json")
    finally:
        run(
            "docker",
            "compose",
            "exec",
            "-T",
            "-u",
            "root",
            "n8n",
            "rm",
            "-f",
            "/tmp/credentials.json",
        )
    n8n("import:workflow", "--input=/workflows/kbtu-dean-email-drafts.json")

    # n8n 2.x: publish:workflow; 1.x: update:workflow --active=true
    if n8n("publish:workflow", f"--id={WORKFLOW_ID}", check=False).returncode:
        n8n("update:workflow", f"--id={WORKFLOW_ID}", "--active=true")
    run("docker", "compose", "restart", "n8n")
    print(
        "Готово: воркфлоу включён, новые письма в "
        f"{address} получат черновик ответа.\n"
        "Backend должен быть запущен (после изменения .env — перезапущен): "
        ".venv\\Scripts\\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000"
    )


if __name__ == "__main__":
    main()
