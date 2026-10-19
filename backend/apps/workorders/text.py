"""
Arthasee — Work Order text helpers

16 Oct 2026 (Phase 21, Task 21.1). Made's rule, 12 Sep note: "Di WO tidak
boleh muncul harga!" Before this date, Estimate.approve() folded the quoted
labor price into a WorkOrderJobLine's description, e.g.
"Tune-up (estimasi Rp 350.000)". New approvals no longer do that, but older
rows still hold the suffix in the database. Rather than rewrite production
data, every surface that shows a job line strips it on the way out:
the job ticket PDF (apps.workorders.pdf), the WO API serializer
(apps.workorders.serializers) and the customer tracking payload
(apps.customers.payload). One regex, one place.

Deliberately dependency-free (no xhtml2pdf, no models), so any module can
import it cheaply.
"""
import re

# Matched loosely on the "(estimasi Rp ...)" shape, at the end of the text,
# rather than a specific number format.
PRICE_SUFFIX_RE = re.compile(r"\s*\(estimasi\s+Rp[^)]*\)\s*$", re.IGNORECASE)


def strip_price_suffix(description):
    if not description:
        return description
    return PRICE_SUFFIX_RE.sub("", description).strip()
