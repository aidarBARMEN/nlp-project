import json
import logging

from ingestion.models import utcnow

logger = logging.getLogger("kbtu.ingestion")


def event(name: str, **fields) -> None:
    # Only identifiers/counts, never document text or credentials.
    logger.info(json.dumps({"event": name, "at": utcnow().isoformat(), **fields}))
