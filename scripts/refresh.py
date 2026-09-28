"""One scheduled refresh; run from the checkout using its virtual environment."""

import subprocess
import sys
from pathlib import Path

from ingestion.config import Settings


def main():
    settings = Settings()
    commands = [["crawl-kbtu"]]
    for channel, folder in (("telegram", "telegram"), ("manual_upload", "manual")):
        path = settings.data_dir / "inbox" / folder
        path.mkdir(parents=True, exist_ok=True)
        commands.append(["ingest-folder", str(path.resolve()), "--source-channel", channel])
    commands.extend([["refresh-current"], ["verify"]])
    failed = False
    for command in commands:
        result = subprocess.run(
            [sys.executable, "-m", "ingestion.cli", *command],
            cwd=Path(__file__).resolve().parents[1],
            check=False,
        )
        failed |= result.returncode != 0
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
