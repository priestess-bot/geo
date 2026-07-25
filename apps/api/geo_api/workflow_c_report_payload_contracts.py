"""Positive transport contract for Customer-visible Workflow C report content."""

from __future__ import annotations

from typing import Annotated, NotRequired, TypedDict

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_serializer,
    model_validator,
)

from geo_core.workflow_c_reports import (
    WorkflowCCustomerMetricKey,
    WorkflowCCustomerReportPayload,
)


CustomerText = Annotated[str, StringConstraints(strict=True, min_length=1)]
CustomerHeadline = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=200)
]
CustomerLongText = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=2_000)
]
CustomerDecimalText = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=64)
]
CustomerMetricValue = int | float | CustomerDecimalText
CustomerWarning = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=500)]


class WorkflowCCustomerSafePayloadSerialized(TypedDict):
    headline: CustomerHeadline
    summary: NotRequired[CustomerLongText]
    methodology: NotRequired[CustomerLongText]
    warnings: NotRequired[Annotated[list[CustomerWarning], Field(min_length=1, max_length=20)]]
    mention_rate: NotRequired[CustomerMetricValue]
    recommendation_rate: NotRequired[CustomerMetricValue]
    metrics: NotRequired[
        Annotated[
            dict[WorkflowCCustomerMetricKey, CustomerMetricValue],
            Field(min_length=1, max_length=32),
        ]
    ]


class WorkflowCCustomerSafePayload(BaseModel):
    """Only aggregate prose and known scalar metrics may reach Customer clients."""

    model_config = ConfigDict(extra="forbid", strict=True)

    headline: CustomerText = Field(max_length=200)
    summary: CustomerText | None = Field(default=None, max_length=2_000)
    methodology: CustomerText | None = Field(default=None, max_length=2_000)
    warnings: list[CustomerWarning] | None = Field(default=None, min_length=1, max_length=20)
    mention_rate: CustomerMetricValue | None = None
    recommendation_rate: CustomerMetricValue | None = None
    metrics: dict[WorkflowCCustomerMetricKey, CustomerMetricValue] | None = Field(
        default=None, min_length=1, max_length=32
    )

    @model_validator(mode="before")
    @classmethod
    def enforce_domain_contract(cls, value: object) -> dict[str, object]:
        return WorkflowCCustomerReportPayload.from_mapping(value).to_dict()

    def to_domain(self) -> WorkflowCCustomerReportPayload:
        return WorkflowCCustomerReportPayload.from_mapping(
            {
                key: value
                for key, value in (
                    ("headline", self.headline),
                    ("summary", self.summary),
                    ("methodology", self.methodology),
                    ("warnings", self.warnings),
                    ("mention_rate", self.mention_rate),
                    ("recommendation_rate", self.recommendation_rate),
                    ("metrics", self.metrics),
                )
                if value is not None
            }
        )

    @model_serializer(mode="plain", return_type=WorkflowCCustomerSafePayloadSerialized)
    def serialize_payload(self) -> WorkflowCCustomerSafePayloadSerialized:
        result: WorkflowCCustomerSafePayloadSerialized = {"headline": self.headline}
        if self.summary is not None:
            result["summary"] = self.summary
        if self.methodology is not None:
            result["methodology"] = self.methodology
        if self.warnings is not None:
            result["warnings"] = list(self.warnings)
        if self.mention_rate is not None:
            result["mention_rate"] = self.mention_rate
        if self.recommendation_rate is not None:
            result["recommendation_rate"] = self.recommendation_rate
        if self.metrics is not None:
            result["metrics"] = dict(self.metrics)
        return result


__all__ = ["WorkflowCCustomerSafePayload"]
