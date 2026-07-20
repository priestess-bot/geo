"""Canonical monitoring capture methods, platforms and surface registry."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping


class CaptureMethod(StrEnum):
    OFFICIAL_REPORT_IMPORT = "official_report_import"
    MANUAL_UI = "manual_ui"
    PROVIDER_API = "provider_api"
    PROXY_GROUNDED_API = "proxy_grounded_api"
    SYNTHETIC = "synthetic"
    UNKNOWN = "unknown"


PUBLIC_OBSERVATION_CAPTURE_METHODS = frozenset(
    {
        CaptureMethod.MANUAL_UI,
        CaptureMethod.PROVIDER_API,
        CaptureMethod.PROXY_GROUNDED_API,
    }
)


class ObservationPlatform(StrEnum):
    OPENAI = "openai"
    GOOGLE = "google"
    PERPLEXITY = "perplexity"
    MICROSOFT = "microsoft"
    ANTHROPIC = "anthropic"
    OTHER = "other"


class SurfaceKind(StrEnum):
    CONSUMER_UI = "consumer_ui"
    OFFICIAL_REPORT = "official_report"
    PROVIDER_API = "provider_api"
    GROUNDED_PROXY = "grounded_proxy"
    INTERNAL_BENCHMARK = "internal_benchmark"
    OTHER = "other"


class ObservationSurface(StrEnum):
    CHATGPT_SEARCH = "chatgpt_search"
    GOOGLE_SEARCH = "google_search"
    GOOGLE_AI_OVERVIEWS = "google_ai_overviews"
    GOOGLE_AI_MODE = "google_ai_mode"
    GEMINI = "gemini"
    PERPLEXITY_ANSWER = "perplexity_answer"
    BING_SEARCH = "bing_search"
    BING_COPILOT = "bing_copilot"
    CLAUDE_AI = "claude_ai"
    OPENAI_API = "openai_api"
    GOOGLE_GEMINI_API = "google_gemini_api"
    PERPLEXITY_API = "perplexity_api"
    ANTHROPIC_API = "anthropic_api"
    MICROSOFT_FOUNDRY_BING_GROUNDING = "microsoft_foundry_bing_grounding"
    GOOGLE_VERTEX_GROUNDING = "google_vertex_grounding"
    GOOGLE_GENERATIVE_AI_PERFORMANCE_REPORT = "google_generative_ai_performance_report"
    BING_AI_PERFORMANCE_REPORT = "bing_ai_performance_report"
    INTERNAL_BENCHMARK = "internal_benchmark"
    OTHER = "other"


@dataclass(frozen=True)
class SurfaceDefinition:
    platform: ObservationPlatform | None
    kind: SurfaceKind


SURFACE_DEFINITIONS: Mapping[ObservationSurface, SurfaceDefinition] = MappingProxyType(
    {
        ObservationSurface.CHATGPT_SEARCH: SurfaceDefinition(
            ObservationPlatform.OPENAI, SurfaceKind.CONSUMER_UI
        ),
        ObservationSurface.GOOGLE_SEARCH: SurfaceDefinition(
            ObservationPlatform.GOOGLE, SurfaceKind.CONSUMER_UI
        ),
        ObservationSurface.GOOGLE_AI_OVERVIEWS: SurfaceDefinition(
            ObservationPlatform.GOOGLE, SurfaceKind.CONSUMER_UI
        ),
        ObservationSurface.GOOGLE_AI_MODE: SurfaceDefinition(
            ObservationPlatform.GOOGLE, SurfaceKind.CONSUMER_UI
        ),
        ObservationSurface.GEMINI: SurfaceDefinition(
            ObservationPlatform.GOOGLE, SurfaceKind.CONSUMER_UI
        ),
        ObservationSurface.PERPLEXITY_ANSWER: SurfaceDefinition(
            ObservationPlatform.PERPLEXITY, SurfaceKind.CONSUMER_UI
        ),
        ObservationSurface.BING_SEARCH: SurfaceDefinition(
            ObservationPlatform.MICROSOFT, SurfaceKind.CONSUMER_UI
        ),
        ObservationSurface.BING_COPILOT: SurfaceDefinition(
            ObservationPlatform.MICROSOFT, SurfaceKind.CONSUMER_UI
        ),
        ObservationSurface.CLAUDE_AI: SurfaceDefinition(
            ObservationPlatform.ANTHROPIC, SurfaceKind.CONSUMER_UI
        ),
        ObservationSurface.OPENAI_API: SurfaceDefinition(
            ObservationPlatform.OPENAI, SurfaceKind.PROVIDER_API
        ),
        ObservationSurface.GOOGLE_GEMINI_API: SurfaceDefinition(
            ObservationPlatform.GOOGLE, SurfaceKind.PROVIDER_API
        ),
        ObservationSurface.PERPLEXITY_API: SurfaceDefinition(
            ObservationPlatform.PERPLEXITY, SurfaceKind.PROVIDER_API
        ),
        ObservationSurface.ANTHROPIC_API: SurfaceDefinition(
            ObservationPlatform.ANTHROPIC, SurfaceKind.PROVIDER_API
        ),
        ObservationSurface.MICROSOFT_FOUNDRY_BING_GROUNDING: SurfaceDefinition(
            ObservationPlatform.MICROSOFT, SurfaceKind.GROUNDED_PROXY
        ),
        ObservationSurface.GOOGLE_VERTEX_GROUNDING: SurfaceDefinition(
            ObservationPlatform.GOOGLE, SurfaceKind.GROUNDED_PROXY
        ),
        ObservationSurface.GOOGLE_GENERATIVE_AI_PERFORMANCE_REPORT: SurfaceDefinition(
            ObservationPlatform.GOOGLE, SurfaceKind.OFFICIAL_REPORT
        ),
        ObservationSurface.BING_AI_PERFORMANCE_REPORT: SurfaceDefinition(
            ObservationPlatform.MICROSOFT, SurfaceKind.OFFICIAL_REPORT
        ),
        ObservationSurface.INTERNAL_BENCHMARK: SurfaceDefinition(
            None, SurfaceKind.INTERNAL_BENCHMARK
        ),
        ObservationSurface.OTHER: SurfaceDefinition(None, SurfaceKind.OTHER),
    }
)


CAPTURE_SURFACE_KIND: Mapping[CaptureMethod, SurfaceKind] = MappingProxyType(
    {
        CaptureMethod.OFFICIAL_REPORT_IMPORT: SurfaceKind.OFFICIAL_REPORT,
        CaptureMethod.MANUAL_UI: SurfaceKind.CONSUMER_UI,
        CaptureMethod.PROVIDER_API: SurfaceKind.PROVIDER_API,
        CaptureMethod.PROXY_GROUNDED_API: SurfaceKind.GROUNDED_PROXY,
        CaptureMethod.SYNTHETIC: SurfaceKind.INTERNAL_BENCHMARK,
        CaptureMethod.UNKNOWN: SurfaceKind.OTHER,
    }
)
