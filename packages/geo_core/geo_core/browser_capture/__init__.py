"""Governed consumer-surface Browser Capture."""

from geo_core.browser_capture.admission import BrowserCaptureAttemptAdmissionService
from geo_core.browser_capture.domain import (
    BrowserCaptureError,
    EgressObservation,
    EgressOutcome,
    EgressVerification,
    NetworkType,
    evaluate_egress,
)

__all__ = [
    "BrowserCaptureAttemptAdmissionService",
    "BrowserCaptureError",
    "EgressObservation",
    "EgressOutcome",
    "EgressVerification",
    "NetworkType",
    "evaluate_egress",
]
