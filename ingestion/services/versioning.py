import re
from datetime import date

from ingestion.models import CanonicalDocument

TRUST_RANK = {"unverified": 0, "verified_internal": 1, "official": 2}


def current_version(documents: list[CanonicalDocument], today: date | None = None):
    today = today or date.today()
    eligible = [
        d
        for d in documents
        if (not d.effective_from or d.effective_from <= today)
        and (not d.effective_to or today <= d.effective_to)
    ]
    if not eligible:
        return None

    def rank(doc):
        version = tuple(int(n) for n in re.findall(r"\d+", doc.version or ""))
        year = int(doc.academic_year[:4]) if doc.academic_year else 0
        effective = doc.effective_from.toordinal() if doc.effective_from else 0
        # Explicit dates/versions beat an undated import; fetch time only breaks ties.
        return TRUST_RANK[doc.trust_level], effective, year, version, doc.fetched_at, doc.doc_id

    return max(eligible, key=rank)
