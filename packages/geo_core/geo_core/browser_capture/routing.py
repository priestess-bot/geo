"""Stable broker identities for the isolated Browser Capture worker."""

BROWSER_CAPTURE_QUEUE = "browser-capture"
BROWSER_CAPTURE_ACTOR = "process_browser_capture_job"
BROWSER_CAPTURE_JOB_KIND = "browser.capture"
BROWSER_EGRESS_TEST_JOB_KIND = "browser.egress_test"
BROWSER_CAPTURE_OUTBOX_TOPICS = frozenset({"browser.capture", "browser.egress_test"})

__all__ = [
    "BROWSER_CAPTURE_ACTOR",
    "BROWSER_CAPTURE_JOB_KIND",
    "BROWSER_CAPTURE_OUTBOX_TOPICS",
    "BROWSER_CAPTURE_QUEUE",
    "BROWSER_EGRESS_TEST_JOB_KIND",
]
