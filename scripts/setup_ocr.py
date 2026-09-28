"""Install official Tesseract language data for PyMuPDF's integrated OCR engine."""

import argparse
import hashlib
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import urlopen
from uuid import uuid4

from dotenv import set_key

from ingestion.config import PROJECT_DIR, Settings
from ingestion.storage import write_json

# Fixed upstream revision: language data only, no executable installer or system changes.
REVISION = "87416418657359cb625c412a48b6e1d6d41c29bd"
BASE_URL = f"https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/{REVISION}"


def install_language(language: str, directory: Path) -> dict:
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,30}", language):
        raise ValueError(f"Invalid OCR language: {language}")
    target = directory / f"{language}.traineddata"
    if target.exists() and target.stat().st_size > 100_000:
        data = target.read_bytes()
    else:
        with urlopen(f"{BASE_URL}/{language}.traineddata", timeout=45) as response:
            data = response.read(50 * 1024 * 1024 + 1)
        if not 100_000 < len(data) <= 50 * 1024 * 1024:
            raise ValueError(f"Unexpected OCR language data size: {language}")
        temporary = target.with_name(f".{language}.{uuid4().hex}.part")
        try:
            temporary.write_bytes(data)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    return {"language": language, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Подготовка OCR для PDF-сканов")
    parser.add_argument("--enable", action="store_true", help="включить OCR в корневом .env")
    args = parser.parse_args()
    settings = Settings()
    directory = settings.ocr_tessdata or settings.data_dir / "tessdata"
    directory.mkdir(parents=True, exist_ok=True)
    languages = list(dict.fromkeys(settings.ocr_languages.split("+")))
    with ThreadPoolExecutor(max_workers=3) as executor:
        installed = list(executor.map(lambda lang: install_language(lang, directory), languages))
    report = {"directory": str(directory), "source": BASE_URL, "languages": installed}
    write_json(directory / "manifest.json", report)
    if args.enable:
        env_file = PROJECT_DIR / ".env"
        set_key(str(env_file), "OCR_ENABLED", "true", quote_mode="never")
        set_key(str(env_file), "OCR_TESSDATA", directory.as_posix(), quote_mode="always")
        report["message"] = "OCR включён. Перезапустите backend и нажмите «Обновить базу»."
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
