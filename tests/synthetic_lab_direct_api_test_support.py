"""In-memory direct-generation behavior shared by Synthetic Lab API tests."""

from __future__ import annotations

import hashlib
from uuid import UUID, uuid4


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _values(payload: object) -> dict[str, object]:
    return payload.model_dump(mode="python")


class SyntheticLabDirectApiMixin:
    def direct_generation_options(self, principal, **values: object):
        self._check(principal, values["project_id"])
        subject_id = UUID("e424d8ac-0000-4000-8000-000000000001")
        evidence_id = UUID("e424d8ac-0000-4000-8000-000000000002")
        knowledge = {
            "evidence_id": evidence_id,
            "kind": "citation",
            "subject_entity_id": subject_id,
            "subject_name": "ADVINSYS TerraMow V600",
            "summary": "The V600 is listed for lawns up to 600 square metres.",
            "snapshot_hash": _hash("v600-evidence"),
            "source_title": "ADVINSYS V600 official page",
            "source_url": "https://www.advinsys.com.au/products/v600",
        }
        return {
            "subjects": (
                {
                    "id": subject_id,
                    "name": "ADVINSYS TerraMow V600",
                    "canonical_url": "https://www.advinsys.com.au/products/v600",
                    "knowledge_snapshot_hash": _hash("v600-knowledge"),
                    "knowledge_items": (knowledge,),
                    "competitor_knowledge_snapshot_hash": None,
                    "competitor_knowledge_items": (knowledge,),
                },
            ),
            "channel_styles": tuple(self.channel_styles.values()),
            "has_competitor_knowledge": False,
        }

    def list_channel_styles(self, principal, **values: object):
        self._check(principal, values["project_id"])
        items = list(self.channel_styles.values())
        channel = values.get("channel")
        if channel is not None:
            items = [item for item in items if item["channel"] == channel]
        return self._page(items, int(values["limit"]), int(values["offset"]))

    def create_channel_style(self, principal, **values: object):
        self._check(principal, values["project_id"])
        request = _values(values["payload"])
        channel = str(values["channel"])
        previous = self.channel_styles.get(channel)
        version = int(request["expected_current_version"]) + 1
        item = {
            "id": uuid4(),
            "project_id": values["project_id"],
            "style_id": previous["style_id"] if previous else uuid4(),
            "version_number": version,
            "previous_version_id": previous["id"] if previous else None,
            "channel": channel,
            "locale": "en-AU",
            "directive": request["directive"],
            "provenance": "manual_initial" if previous is None else "manual_edit",
            "calibration_status": "pending_sample_calibration",
            "style_hash": _hash(f"style:{channel}:{version}:{request['directive']}"),
            "replayed": False,
        }
        self.channel_styles[channel] = item
        return item

    def enqueue_direct_generation(self, principal, **values: object):
        self._check(principal, values["project_id"])
        payload = _values(values["payload"])
        return self._enqueue_memory_job(
            project_id=values["project_id"],
            kind="candidate_generation",
            seed=f"direct:{payload['channel']}:{payload['subject_entity_id']}",
        )

    def list_jobs(self, principal, **values: object):
        self._check(principal, values["project_id"])
        items = list(self.jobs.values())
        if values.get("kind") is not None:
            items = [item for item in items if item["kind"] == values["kind"]]
        if values.get("status") is not None:
            items = [item for item in items if item["status"] == values["status"]]
        return self._page(items, int(values["limit"]), int(values["offset"]))

    def get_job_result(self, principal, **values: object):
        self._check(principal, values["project_id"])
        job_id = values["job_id"]
        if job_id not in self.jobs:
            raise KeyError(job_id)
        review_run_id = uuid4()
        suite_id = uuid4()
        case_id = uuid4()
        profile_id = uuid4()
        fact_id = uuid4()
        runtime_id = uuid4()
        candidate_id = uuid4()
        evaluation_id = uuid4()
        batch_id = uuid4()
        lineage = {"provider": "dify", "configured_model": "deepseek-chat"}
        return {
            "job_id": job_id,
            "task": {
                "case": {
                    "review_suite_version_id": suite_id,
                    "id": case_id,
                    "case_key": "au-buyer-value",
                    "channel": "reddit",
                    "mode": "guided_scenario",
                    "competitor_scenario": True,
                    "profile_version_id": profile_id,
                    "fact_snapshot_id": fact_id,
                },
                "style_pass_threshold": 4.2,
                "prompts": {"generation": {"runtime_option_id": runtime_id}},
            },
            "result": {
                "project_id": values["project_id"],
                "review_run_id": review_run_id,
                "review_case_id": case_id,
                "resolved_candidate_text": "A concise Australian buyer review.",
                "resolution": {
                    "candidate_id": candidate_id,
                    "status": "completed_with_warning",
                    "warning_codes": ("derived_or_unknown",),
                    "failure_code": None,
                },
                "result_hash": _hash("review-result"),
                "batches": (
                    {
                        "id": batch_id,
                        "batch_number": 1,
                        "kind": "initial",
                        "scenario_mode": "guided_scenario",
                        "candidates": tuple({"id": uuid4()} for _ in range(4)),
                        "call_lineage": lineage,
                    },
                ),
                "evaluations": (
                    {
                        "id": evaluation_id,
                        "candidate_id": candidate_id,
                        "candidate_output_hash": _hash("candidate"),
                        "style_score": 4.6,
                        "style_passed": True,
                        "disposition": "warning",
                        "correctable_issue_codes": (),
                        "soft_issue_codes": (),
                        "warning_codes": ("derived_or_unknown",),
                        "claim_assessments": (
                            {
                                "claim_hash": _hash("claim"),
                                "status": "derived_or_unknown",
                                "fact_id": None,
                                "fact_hash": None,
                                "expected_subject_id": None,
                                "observed_subject_id": None,
                                "output_annotation": "derived_or_unknown",
                            },
                        ),
                        "call_lineage": lineage,
                        "evidence_artifact_hash": _hash("evaluation-evidence"),
                    },
                ),
                "revisions": (),
                "model_call_ids": (),
                "workflow_attempt_ids": (uuid4(),),
            },
        }


__all__ = ["SyntheticLabDirectApiMixin"]
