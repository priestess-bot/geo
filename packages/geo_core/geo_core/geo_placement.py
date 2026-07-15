"""Runtime repository for the GEO v3 manual placement workflow.

The repository deliberately exposes state-transition commands instead of generic
table updates. Third-party publication is always recorded as a human action.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from psycopg.rows import dict_row

from geo_core.knowledge_application import deepseek_generate_knowledge_application, load_deepseek_api_key


class GeoPlacementError(ValueError):
    pass


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _text(value: object, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise GeoPlacementError(f"{field} is required")
    return normalized


_PROMPT_VARIABLE = re.compile(r"{{\s*([a-zA-Z0-9_]+)\s*}}")


def _render_prompt(template: str, variables: dict[str, object]) -> str:
    missing: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        value = variables.get(name)
        if value is None:
            missing.add(name)
            return ""
        if isinstance(value, (dict, list, tuple)):
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        return str(value)

    rendered = _PROMPT_VARIABLE.sub(replace, template).strip()
    if missing:
        raise GeoPlacementError(f"prompt template is missing variables: {', '.join(sorted(missing))}")
    return rendered


def _normalize_evidence(items: list[dict[str, object]], *, product_name: str) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    for index, item in enumerate(items, start=1):
        text = _text(item.get("text") or item.get("statement"), f"evidence[{index}].text")
        source_url = _text(item.get("source_url"), f"evidence[{index}].source_url")
        if not source_url.startswith("https://"):
            raise GeoPlacementError("approved evidence requires an HTTPS source URL")
        source_kind = str(item.get("source_kind") or "").strip()
        if source_kind not in {"brand_authored", "editorial", "verified_experience"}:
            raise GeoPlacementError("evidence source_kind must be brand_authored, editorial, or verified_experience")
        usage_rights = str(item.get("usage_rights") or "").strip()
        if usage_rights not in {"owned", "licensed", "public_reference"}:
            raise GeoPlacementError("evidence usage_rights must be explicitly approved")
        if item.get("public_disclosure_allowed") is not True:
            raise GeoPlacementError("evidence must be approved for public disclosure")
        subject = _text(item.get("subject") or product_name, f"evidence[{index}].subject")
        role = str(item.get("subject_role") or "primary_product").strip()
        if role not in {"primary_brand", "primary_product", "competitor", "market", "neutral"}:
            raise GeoPlacementError("evidence subject_role is invalid")
        fingerprint = _hash({"source_url": source_url, "text": text, "subject": subject, "subject_role": role})
        normalized.append({
            "id": str(item.get("id") or fingerprint), "text": text, "source_url": source_url,
            "source_kind": source_kind, "usage_rights": usage_rights,
            "public_disclosure_allowed": True, "public_source_url": str(item.get("public_source_url") or source_url),
            "subject": subject, "subject_role": role, "source_hash": str(item.get("source_hash") or fingerprint),
        })
    return normalized


def _normalize_claims(raw_claims: object, *, evidence: list[dict[str, object]]) -> list[dict[str, object]]:
    evidence_by_id = {str(item["id"]): item for item in evidence}
    claims: list[dict[str, object]] = []
    for index, raw in enumerate(raw_claims if isinstance(raw_claims, list) else [], start=1):
        if not isinstance(raw, dict):
            raise GeoPlacementError("claim inventory entries must be objects")
        claim_text = _text(raw.get("text") or raw.get("claim"), f"claim[{index}].text")
        refs = raw.get("evidence_ids") or raw.get("evidence_refs") or []
        if isinstance(refs, str):
            refs = [refs]
        evidence_ids = [str(value) for value in refs if str(value) in evidence_by_id]
        status = "supported" if evidence_ids else "unsupported"
        claims.append({"text": claim_text, "evidence_ids": evidence_ids, "support_status": status})
    if not claims:
        raise GeoPlacementError("model output must include a non-empty factual claim inventory")
    return claims


class GeoPlacementRepository:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def _one(self, sql: str, params: tuple[object, ...]) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(sql, params)
            row = cursor.fetchone()
        if row is None:
            raise GeoPlacementError("requested GEO record was not found in this project")
        return dict(row)

    def _page(self, sql: str, params: tuple[object, ...]) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(sql, params)
            rows = [dict(row) for row in cursor.fetchall()]
        return {"total_count": len(rows), "records": rows}

    def _commit(self) -> None:
        self.connection.commit()

    def create_product(self, *, project_id: str, actor_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        record = self._one(
            """
            INSERT INTO geo_products(project_id, brand_entity_id, name, canonical_url, category,
                market_code, external_locale, facts, status, created_by)
            VALUES (%s::uuid, NULLIF(%s, '')::uuid, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
            RETURNING *
            """,
            (project_id, str(payload.get("brand_entity_id") or ""), _text(payload.get("name"), "name"),
             _text(payload.get("canonical_url"), "canonical_url"), _text(payload.get("category"), "category"),
             _text(payload.get("market_code") or "AU", "market_code"), "en-AU",
             json.dumps(payload.get("facts") or {}), str(payload.get("status") or "active"), actor_id),
        )
        self._commit()
        return record

    def list_products(self, *, project_id: str) -> dict[str, Any]:
        return self._page("SELECT * FROM geo_products WHERE project_id=%s::uuid ORDER BY updated_at DESC", (project_id,))

    def create_campaign(self, *, project_id: str, actor_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        product_id = _text(payload.get("product_id"), "product_id")
        self._one("SELECT id FROM geo_products WHERE id=%s::uuid AND project_id=%s::uuid", (product_id, project_id))
        record = self._one(
            """
            INSERT INTO geo_campaigns_runtime(project_id, product_id, name, market_code, external_locale,
                forbidden_claims, status, created_by, updated_by)
            VALUES (%s::uuid, %s::uuid, %s, %s, 'en-AU', %s::text[], %s, %s, %s) RETURNING *
            """,
            (project_id, product_id, _text(payload.get("name"), "name"), _text(payload.get("market_code") or "AU", "market_code"),
             list(payload.get("forbidden_claims") or []), str(payload.get("status") or "draft"), actor_id, actor_id),
        )
        self._commit()
        return record

    def list_campaigns(self, *, project_id: str) -> dict[str, Any]:
        return self._page(
            """SELECT c.*, p.name AS product_name, p.canonical_url AS product_url
               FROM geo_campaigns_runtime c JOIN geo_products p ON p.id=c.product_id
               WHERE c.project_id=%s::uuid ORDER BY c.updated_at DESC""", (project_id,)
        )

    def create_campaign_query(self, *, project_id: str, campaign_id: str, actor_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        campaign = self._one("SELECT * FROM geo_campaigns_runtime WHERE id=%s::uuid AND project_id=%s::uuid", (campaign_id, project_id))
        record = self._one(
            """INSERT INTO geo_campaign_queries(project_id, campaign_id, query_text, platform, market_code,
                   locale, device, sample_size, suggested_by)
               VALUES (%s::uuid, %s::uuid, %s, %s, %s, 'en-AU', %s, %s, %s) RETURNING *""",
            (project_id, campaign_id, _text(payload.get("query_text"), "query_text"),
             _text(payload.get("platform"), "platform"), str(campaign["market_code"]),
             str(payload.get("device") or "desktop"), int(payload.get("sample_size") or 3), actor_id),
        )
        self._commit()
        return record

    def list_campaign_queries(self, *, project_id: str, campaign_id: str) -> dict[str, Any]:
        return self._page("SELECT * FROM geo_campaign_queries WHERE project_id=%s::uuid AND campaign_id=%s::uuid ORDER BY created_at DESC", (project_id, campaign_id))

    def approve_campaign_query(self, *, project_id: str, query_id: str, actor_id: str) -> dict[str, Any]:
        record = self._one(
            """UPDATE geo_campaign_queries SET status='approved', approved_by=%s, approved_at=now(), frozen_at=now()
               WHERE id=%s::uuid AND project_id=%s::uuid AND status='suggested' RETURNING *""",
            (actor_id, query_id, project_id),
        )
        self._commit()
        return record

    def import_observation(self, *, project_id: str, actor_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        query_id = _text(payload.get("campaign_query_id"), "campaign_query_id")
        query = self._one("SELECT * FROM geo_campaign_queries WHERE id=%s::uuid AND project_id=%s::uuid", (query_id, project_id))
        if query["status"] != "approved":
            raise GeoPlacementError("only an approved campaign query can receive an observation")
        record = self._one(
            """INSERT INTO geo_observations(project_id, campaign_query_id, observation_phase, sample_index,
                  observed_at, raw_answer, citations, artifact_url, visible_model, market_code, locale, device, imported_by)
               VALUES (%s::uuid,%s::uuid,%s,%s,COALESCE(%s::timestamptz,now()),%s,%s::jsonb,%s,%s,%s,%s,%s,%s)
               RETURNING *""",
            (project_id, query_id, str(payload.get("observation_phase") or "baseline"), int(payload.get("sample_index") or 1),
             payload.get("observed_at"), _text(payload.get("raw_answer"), "raw_answer"), json.dumps(payload.get("citations") or []),
             payload.get("artifact_url"), payload.get("visible_model"), query["market_code"], query["locale"], query["device"], actor_id),
        )
        self._commit()
        return record

    def list_observations(self, *, project_id: str, campaign_id: str) -> dict[str, Any]:
        return self._page(
            """SELECT o.*, q.query_text, q.platform FROM geo_observations o
               JOIN geo_campaign_queries q ON q.id=o.campaign_query_id
               WHERE o.project_id=%s::uuid AND q.campaign_id=%s::uuid ORDER BY o.observed_at DESC""", (project_id, campaign_id)
        )

    def list_publishers(self) -> dict[str, Any]:
        return self._page("SELECT * FROM geo_publishers ORDER BY canonical_domain", ())

    def review_publisher(self, *, publisher_id: str, actor_id: str, status: str, policy_snapshot: dict[str, object]) -> dict[str, Any]:
        if status not in {"approved", "restricted", "prohibited"}:
            raise GeoPlacementError("publisher status must be approved, restricted, or prohibited")
        if not policy_snapshot.get("reviewed_rules") or not policy_snapshot.get("identity_requirement"):
            raise GeoPlacementError("publisher policy review requires reviewed_rules and identity_requirement")
        record = self._one(
            """UPDATE geo_publishers SET status=%s,policy_snapshot=%s::jsonb,policy_checked_by=%s,
                      policy_checked_at=now(),updated_at=now() WHERE id=%s::uuid RETURNING *""",
            (status, json.dumps(policy_snapshot), actor_id, publisher_id),
        )
        self._commit()
        return record

    def create_destination(self, *, project_id: str, actor_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        policy = dict(payload.get("policy_snapshot") or {})
        record = self._one(
            """INSERT INTO geo_destinations(project_id,publisher_id,name,destination_url,task_type,task_key,ownership_kind,
                   operation_mode,public_disclosure_required,qualification_status,policy_snapshot,policy_hash,created_by,updated_by)
               VALUES (%s::uuid,%s::uuid,%s,%s,%s,%s,%s,%s,%s,'candidate',%s::jsonb,%s,%s,%s) RETURNING *""",
            (project_id, _text(payload.get("publisher_id"), "publisher_id"), _text(payload.get("name"), "name"),
             _text(payload.get("destination_url"), "destination_url"), _text(payload.get("task_type"), "task_type"),
             _text(payload.get("task_key"), "task_key"),
             _text(payload.get("ownership_kind"), "ownership_kind"), str(payload.get("operation_mode") or "manual_submission"),
             bool(payload.get("public_disclosure_required", True)), json.dumps(policy), _hash(policy), actor_id, actor_id),
        )
        self._commit()
        return record

    def qualify_destination(self, *, project_id: str, destination_id: str, actor_id: str) -> dict[str, Any]:
        destination = self._one(
            """SELECT d.*,p.status AS publisher_status FROM geo_destinations d
               JOIN geo_publishers p ON p.id=d.publisher_id WHERE d.id=%s::uuid AND d.project_id=%s::uuid""",
            (destination_id, project_id),
        )
        if destination["publisher_status"] != "approved":
            raise GeoPlacementError("destination cannot be qualified until the publisher policy is approved")
        policy = destination.get("policy_snapshot") or {}
        if not policy.get("notes") or policy.get("automated_posting") != "prohibited":
            raise GeoPlacementError("destination policy must record rules and prohibit automated posting")
        record = self._one(
            """UPDATE geo_destinations SET qualification_status='approved', qualified_by=%s, qualified_at=now(),
                  updated_by=%s, updated_at=now() WHERE id=%s::uuid AND project_id=%s::uuid
                  AND qualification_status='candidate' RETURNING *""", (actor_id, actor_id, destination_id, project_id)
        )
        self._commit()
        return record

    def list_destinations(self, *, project_id: str) -> dict[str, Any]:
        return self._page(
            """SELECT d.*, p.canonical_domain, p.publisher_type FROM geo_destinations d
               JOIN geo_publishers p ON p.id=d.publisher_id WHERE d.project_id=%s::uuid ORDER BY d.updated_at DESC""", (project_id,)
        )

    def create_opportunity(self, *, project_id: str, actor_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        campaign_id = _text(payload.get("campaign_id"), "campaign_id")
        destination_id = _text(payload.get("destination_id"), "destination_id")
        self._one("SELECT id FROM geo_campaigns_runtime WHERE id=%s::uuid AND project_id=%s::uuid", (campaign_id, project_id))
        destination = self._one("SELECT * FROM geo_destinations WHERE id=%s::uuid AND project_id=%s::uuid", (destination_id, project_id))
        if destination["operation_mode"] != "manual_submission" or destination["qualification_status"] != "approved":
            raise GeoPlacementError("placement opportunities require an approved manual-submission destination")
        query_id = str(payload.get("campaign_query_id") or "")
        if query_id:
            self._one(
                "SELECT id FROM geo_campaign_queries WHERE id=%s::uuid AND project_id=%s::uuid AND campaign_id=%s::uuid AND status='approved'",
                (query_id, project_id, campaign_id),
            )
        record = self._one(
            """INSERT INTO geo_placement_opportunities(project_id,campaign_id,destination_id,campaign_query_id,title,rationale,priority,created_by,updated_by)
               VALUES (%s::uuid,%s::uuid,%s::uuid,NULLIF(%s,'')::uuid,%s,%s,%s,%s,%s) RETURNING *""",
            (project_id,campaign_id,destination_id,str(payload.get("campaign_query_id") or ""),_text(payload.get("title"), "title"),
             _text(payload.get("rationale"), "rationale"),str(payload.get("priority") or "medium"),actor_id,actor_id),
        )
        self._commit()
        return record

    def list_opportunities(self, *, project_id: str, campaign_id: str) -> dict[str, Any]:
        return self._page(
            """SELECT o.*, d.name AS destination_name, d.destination_url, d.task_type,d.task_key
               FROM geo_placement_opportunities o JOIN geo_destinations d ON d.id=o.destination_id
               WHERE o.project_id=%s::uuid AND o.campaign_id=%s::uuid ORDER BY o.priority DESC,o.updated_at DESC""", (project_id,campaign_id)
        )

    def create_prompt_template(self, *, project_id: str, actor_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        template = self._one(
            """INSERT INTO geo_prompt_templates(project_id,task_key,name,status,created_by)
               VALUES (%s::uuid,%s,%s,'draft',%s) RETURNING *""",
            (project_id,_text(payload.get("task_key"),"task_key"),_text(payload.get("name"),"name"),actor_id),
        )
        self._commit()
        return template

    def create_prompt_version(self, *, project_id: str, template_id: str, actor_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._one("SELECT id FROM geo_prompt_templates WHERE id=%s::uuid AND project_id=%s::uuid", (template_id,project_id))
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT COALESCE(max(version_number),0)+1 FROM geo_prompt_template_versions WHERE prompt_template_id=%s::uuid AND project_id=%s::uuid",
                (template_id, project_id),
            )
            version = int(cursor.fetchone()[0])
        material = {"system": _text(payload.get("system_template"), "system_template"), "user": _text(payload.get("user_template"), "user_template"), "schema": payload.get("output_schema") or {}}
        record = self._one(
            """INSERT INTO geo_prompt_template_versions(project_id,prompt_template_id,version_number,system_template,user_template,output_schema,template_hash,status,created_by)
               VALUES (%s::uuid,%s::uuid,%s,%s,%s,%s::jsonb,%s,%s,%s) RETURNING *""",
            (project_id,template_id,version,material["system"],material["user"],json.dumps(material["schema"]),_hash(material),str(payload.get("status") or "draft"),actor_id),
        )
        self._commit()
        return record

    def publish_prompt_template(self, *, project_id: str, template_id: str, actor_id: str, version_id: str | None = None) -> dict[str, Any]:
        template = self._one(
            """UPDATE geo_prompt_templates SET status='published',updated_at=now()
               WHERE id=%s::uuid AND project_id=%s::uuid AND status IN ('draft','published') RETURNING *""",
            (template_id, project_id),
        )
        if version_id:
            selected = self._one(
                """SELECT id FROM geo_prompt_template_versions WHERE prompt_template_id=%s::uuid AND project_id=%s::uuid
                   AND status='draft' AND id=%s::uuid""",
                (template_id, project_id, version_id),
            )
        else:
            selected = self._one(
                """SELECT id FROM geo_prompt_template_versions WHERE prompt_template_id=%s::uuid AND project_id=%s::uuid
                   AND status='draft' ORDER BY version_number DESC LIMIT 1""",
                (template_id, project_id),
            )
        with self.connection.cursor() as cursor:
            cursor.execute(
                "UPDATE geo_prompt_template_versions SET status='archived' WHERE prompt_template_id=%s::uuid AND project_id=%s::uuid AND status='published'",
                (template_id, project_id),
            )
            cursor.execute(
                "UPDATE geo_prompt_template_versions SET status='published' WHERE id=%s::uuid AND project_id=%s::uuid",
                (selected["id"], project_id),
            )
        self._commit()
        return template

    def list_prompt_templates(self, *, project_id: str) -> dict[str, Any]:
        return self._page(
            """SELECT t.*, COALESCE(json_agg(v ORDER BY v.version_number DESC) FILTER (WHERE v.id IS NOT NULL),'[]'::json) AS versions
               FROM geo_prompt_templates t LEFT JOIN geo_prompt_template_versions v ON v.prompt_template_id=t.id
               WHERE t.project_id=%s::uuid GROUP BY t.id ORDER BY t.updated_at DESC""", (project_id,)
        )

    def generate_package(self, *, project_id: str, opportunity_id: str, actor_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        idempotency_key = str(payload.get("idempotency_key") or "").strip() or None
        if idempotency_key:
            with self.connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    "SELECT * FROM geo_placement_packages WHERE project_id=%s::uuid AND opportunity_id=%s::uuid AND idempotency_key=%s",
                    (project_id, opportunity_id, idempotency_key),
                )
                existing = cursor.fetchone()
            if existing is not None:
                return dict(existing)
        opportunity = self._one(
            """SELECT o.*, c.name AS campaign_name,c.market_code,c.external_locale,c.forbidden_claims,
                      p.name AS product_name, p.category, p.canonical_url, p.facts, d.task_type, d.task_key,
                      d.public_disclosure_required, d.policy_snapshot, d.name AS destination_name
               FROM geo_placement_opportunities o JOIN geo_campaigns_runtime c ON c.id=o.campaign_id
               JOIN geo_products p ON p.id=c.product_id JOIN geo_destinations d ON d.id=o.destination_id
               WHERE o.id=%s::uuid AND o.project_id=%s::uuid""", (opportunity_id,project_id)
        )
        raw_evidence = list(payload.get("evidence") or [])
        if not raw_evidence:
            raise GeoPlacementError("a placement package requires at least one approved evidence item")
        evidence = _normalize_evidence(raw_evidence, product_name=str(opportunity["product_name"]))
        prompt_version_id = _text(payload.get("prompt_template_version_id"), "prompt_template_version_id")
        prompt = self._one(
            """SELECT v.*, t.task_key FROM geo_prompt_template_versions v JOIN geo_prompt_templates t ON t.id=v.prompt_template_id
               WHERE v.id=%s::uuid AND v.project_id=%s::uuid AND v.status='published' AND t.status='published'""", (prompt_version_id,project_id)
        )
        if prompt["task_key"] != opportunity["task_key"]:
            raise GeoPlacementError("published prompt task_key does not match the destination task type")
        disclosure = str(payload.get("disclosure_text") or "").strip()
        if opportunity["public_disclosure_required"] and not disclosure:
            raise GeoPlacementError("this destination requires public disclosure text")
        title = str(payload.get("title") or f"{opportunity['product_name']} - {opportunity['destination_name']}").strip()
        rendered_text = str(payload.get("rendered_text") or "").strip()
        prompt_variables: dict[str, object] = {
            "campaign_name": opportunity["campaign_name"], "product_name": opportunity["product_name"],
            "category": opportunity["category"], "market_code": opportunity["market_code"],
            "locale": opportunity["external_locale"], "destination_name": opportunity["destination_name"],
            "task_key": opportunity["task_key"], "disclosure_text": disclosure,
            "evidence": evidence, "product_url": opportunity["canonical_url"],
        }
        rendered_system = _render_prompt(str(prompt["system_template"]), prompt_variables)
        rendered_user = _render_prompt(str(prompt["user_template"]), prompt_variables)
        prompt_bundle = {
            "prompt_template_version_id": prompt_version_id, "template_hash": prompt["template_hash"],
            "system": rendered_system, "user": rendered_user, "output_schema": prompt["output_schema"],
            "variables_hash": _hash(prompt_variables),
        }
        prompt_bundle_hash = _hash(prompt_bundle)
        generation_model = None
        response_hash = None
        model_claims: object = payload.get("claim_inventory") or []
        if bool(payload.get("generate_with_model")):
            api_key = load_deepseek_api_key()
            if not api_key:
                raise GeoPlacementError("DeepSeek API key is not configured for GEO package generation")
            model = str(payload.get("model") or "deepseek-chat").strip()
            model_facts = tuple(
                {
                    "id": str(item["id"]),
                    "subject": str(item["subject"]),
                    "predicate": "is supported by approved source",
                    "object_value": str(item["text"]),
                }
                for item in evidence
            )
            model_output = deepseek_generate_knowledge_application(
                api_key=api_key,
                target_brand=str((opportunity.get("facts") or {}).get("brand") or opportunity["campaign_name"]),
                category=str(opportunity["category"]),
                market_code=str(opportunity["market_code"]),
                facts=model_facts,
                prompts=tuple(),
                generation_type="placement_package",
                content_type=str(opportunity["task_key"]),
                target_platform=str(opportunity["destination_name"]),
                intent_type="consumer_recommendation",
                city=None,
                competitor=None,
                quantity=1,
                template_instruction=f"{rendered_system}\n\nUser instructions:\n{rendered_user}",
                output_schema=dict(prompt["output_schema"]),
                target_audience="Australian consumers comparing products",
                forbidden_claims=tuple(dict.fromkeys([*(str(item) for item in opportunity["forbidden_claims"]), *(str(item) for item in payload.get("forbidden_claims") or [])])),
                model=model,
            )
            rendered_text = str(model_output.get("content_markdown") or "").strip()
            if not rendered_text:
                raise GeoPlacementError("DeepSeek returned no placement content")
            generation_model = str(model_output.get("model") or model)
            response_hash = str(model_output.get("response_hash") or "") or None
            model_claims = model_output.get("claims") or []
        if not rendered_text:
            facts = opportunity.get("facts") or {}
            fact_lines = "\n".join(f"- {key}: {value}" for key, value in facts.items()) or "- Use only the supplied approved evidence."
            rendered_text = f"{title}\n\n{fact_lines}\n\n{disclosure}".strip()
        forbidden = set(str(value).lower() for value in [*opportunity["forbidden_claims"], *(payload.get("forbidden_claims") or [])])
        if any(term and term in rendered_text.lower() for term in forbidden):
            raise GeoPlacementError("generated content contains a campaign-forbidden claim")
        claims = _normalize_claims(model_claims, evidence=evidence)
        qa_status = "passed" if all(item["support_status"] == "supported" for item in claims) else "failed"
        content = {"title": title, "body": rendered_text, "destination": opportunity["destination_name"], "task_key": prompt["task_key"]}
        record = self._one(
            """INSERT INTO geo_placement_packages(project_id,opportunity_id,prompt_template_version_id,task_key,title,content_json,rendered_text,
                   disclosure_text,evidence_snapshot,claim_inventory,prompt_bundle,prompt_bundle_hash,qa_status,content_hash,
                   generation_model,model_response_hash,idempotency_key,created_by)
               VALUES (%s::uuid,%s::uuid,%s::uuid,%s,%s,%s::jsonb,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (project_id,opportunity_id,prompt_version_id,prompt["task_key"],title,json.dumps(content),rendered_text,disclosure,
             json.dumps(evidence),json.dumps(claims),json.dumps(prompt_bundle),prompt_bundle_hash,qa_status,_hash(content),generation_model,
             response_hash,idempotency_key,actor_id),
        )
        self._commit()
        return record

    def list_packages(self, *, project_id: str, campaign_id: str) -> dict[str, Any]:
        return self._page(
            """SELECT p.*, o.campaign_id, d.name AS destination_name,d.destination_url FROM geo_placement_packages p
               JOIN geo_placement_opportunities o ON o.id=p.opportunity_id JOIN geo_destinations d ON d.id=o.destination_id
               WHERE p.project_id=%s::uuid AND o.campaign_id=%s::uuid ORDER BY p.created_at DESC""", (project_id,campaign_id)
        )

    def revise_package(self, *, project_id: str, package_id: str, actor_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        base = self._one(
            "SELECT * FROM geo_placement_packages WHERE id=%s::uuid AND project_id=%s::uuid",
            (package_id, project_id),
        )
        if str(payload.get("base_content_hash") or "") != base["content_hash"]:
            raise GeoPlacementError("base content hash does not match; reload before revising")
        reason = _text(payload.get("reason"), "reason")
        rendered_text = _text(payload.get("rendered_text"), "rendered_text")
        claims = _normalize_claims(payload.get("claim_inventory"), evidence=list(base["evidence_snapshot"]))
        qa_status = "passed" if all(item["support_status"] == "supported" for item in claims) else "failed"
        content = dict(base["content_json"])
        content["body"] = rendered_text
        record = self._one(
            """INSERT INTO geo_placement_packages(project_id,opportunity_id,prompt_template_version_id,task_key,title,
                     content_json,rendered_text,disclosure_text,evidence_snapshot,claim_inventory,prompt_bundle,prompt_bundle_hash,
                     qa_status,content_hash,generation_model,model_response_hash,parent_package_id,version_number,revision_reason,created_by)
               VALUES (%s::uuid,%s::uuid,%s::uuid,%s,%s,%s::jsonb,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s,%s,%s,%s,%s,
                       %s::uuid,%s,%s,%s) RETURNING *""",
            (project_id,base["opportunity_id"],base["prompt_template_version_id"],base["task_key"],base["title"],json.dumps(content),
             rendered_text,base["disclosure_text"],json.dumps(base["evidence_snapshot"]),json.dumps(claims),json.dumps(base["prompt_bundle"]),
             base["prompt_bundle_hash"],qa_status,_hash(content),base["generation_model"],base["model_response_hash"],base["id"],
             int(base["version_number"])+1,reason,actor_id),
        )
        self._one(
            "UPDATE geo_placement_packages SET status='superseded' WHERE id=%s::uuid AND project_id=%s::uuid RETURNING *",
            (package_id, project_id),
        )
        self._commit()
        return record

    def submit_package_review(self, *, project_id: str, package_id: str, actor_id: str) -> dict[str, Any]:
        package = self._one("SELECT qa_status,claim_inventory FROM geo_placement_packages WHERE id=%s::uuid AND project_id=%s::uuid", (package_id,project_id))
        if package["qa_status"] != "passed" or not package["claim_inventory"]:
            raise GeoPlacementError("only a package with a complete supported claim inventory can enter review")
        if any(item.get("support_status") != "supported" for item in package["claim_inventory"]):
            raise GeoPlacementError("unsupported or conflicting claims must be resolved before review")
        record = self._one(
            """UPDATE geo_placement_packages SET status='pending_review',submitted_for_review_by=%s,submitted_for_review_at=now()
               WHERE id=%s::uuid AND project_id=%s::uuid AND status IN ('draft','needs_revision') RETURNING *""", (actor_id,package_id,project_id)
        )
        self._commit()
        return record

    def review_package(self, *, project_id: str, package_id: str, actor_id: str, decision: str, claim_inventory_complete: bool = False, qc_score: float | None = None, review_notes: str = "") -> dict[str, Any]:
        if decision not in {'approved','needs_revision','blocked'}:
            raise GeoPlacementError("review decision must be approved, needs_revision, or blocked")
        package = self._one(
            "SELECT * FROM geo_placement_packages WHERE id=%s::uuid AND project_id=%s::uuid",
            (package_id, project_id),
        )
        if package["status"] != "pending_review":
            raise GeoPlacementError("only a package pending review can be reviewed")
        if package["submitted_for_review_by"] == actor_id:
            raise GeoPlacementError("the person who submitted a package for review cannot approve it")
        if decision == "approved" and not claim_inventory_complete:
            raise GeoPlacementError("approval requires a reviewer to confirm the claim inventory is complete")
        if decision == "approved" and (qc_score is None or qc_score < 85):
            raise GeoPlacementError("approval requires a quality score of at least 85")
        if not review_notes.strip():
            raise GeoPlacementError("review_notes is required")
        record = self._one(
            """UPDATE geo_placement_packages SET status=%s,approved_by=CASE WHEN %s='approved' THEN %s ELSE NULL END,
               approved_at=CASE WHEN %s='approved' THEN now() ELSE NULL END,
               claim_inventory_complete=CASE WHEN %s='approved' THEN TRUE ELSE claim_inventory_complete END,
               claim_inventory_reviewed_by=CASE WHEN %s='approved' THEN %s ELSE claim_inventory_reviewed_by END,
               claim_inventory_reviewed_at=CASE WHEN %s='approved' THEN now() ELSE claim_inventory_reviewed_at END,
               qc_score=%s,review_notes=%s
               WHERE id=%s::uuid AND project_id=%s::uuid AND status='pending_review' RETURNING *""",
            (decision,decision,actor_id,decision,decision,decision,actor_id,decision,qc_score,review_notes.strip(),package_id,project_id)
        )
        self._commit()
        return record

    def create_submission(self, *, project_id: str, package_id: str, actor_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        package = self._one(
            """SELECT p.*,o.destination_id FROM geo_placement_packages p JOIN geo_placement_opportunities o ON o.id=p.opportunity_id
               WHERE p.id=%s::uuid AND p.project_id=%s::uuid""", (package_id,project_id)
        )
        if package['status'] != 'approved':
            raise GeoPlacementError("only an approved package can be recorded as manually submitted")
        record = self._one(
            """INSERT INTO geo_placement_submissions(project_id,placement_package_id,destination_id,submitted_by,submission_evidence_url,external_reference,notes)
               VALUES (%s::uuid,%s::uuid,%s::uuid,%s,%s,%s,%s) RETURNING *""",
            (project_id,package_id,package['destination_id'],actor_id,payload.get('submission_evidence_url'),payload.get('external_reference'),str(payload.get('notes') or '')),
        )
        self._commit()
        return record

    def set_published_url(self, *, project_id: str, submission_id: str, actor_id: str, published_url: str) -> dict[str, Any]:
        record = self._one(
            """UPDATE geo_placement_submissions SET published_url=%s,published_at=now(),status='published_url_pending_verification',notes=notes || %s
               WHERE id=%s::uuid AND project_id=%s::uuid AND status='submitted' RETURNING *""",
            (_text(published_url,'published_url'), f"\nURL supplied by {actor_id}", submission_id,project_id),
        )
        self._commit()
        return record

    def verify_submission(self, *, project_id: str, submission_id: str, actor_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        submission = self._one("SELECT * FROM geo_placement_submissions WHERE id=%s::uuid AND project_id=%s::uuid", (submission_id,project_id))
        if submission['status'] != 'published_url_pending_verification' or not submission['published_url']:
            raise GeoPlacementError("a published URL must be recorded before verification")
        status = str(payload.get('status') or 'failed')
        content_match = bool(payload.get('content_match', False))
        disclosure_match = bool(payload.get('disclosure_match', False))
        if status == 'verified' and not (content_match and disclosure_match):
            raise GeoPlacementError("verified status requires content and disclosure matches")
        verification = self._one(
            """INSERT INTO geo_placement_verifications(project_id,submission_id,status,checked_url,content_match,disclosure_match,details,verified_by)
               VALUES (%s::uuid,%s::uuid,%s,%s,%s,%s,%s::jsonb,%s) RETURNING *""",
            (project_id,submission_id,status,submission['published_url'],content_match,disclosure_match,json.dumps(payload.get('details') or {}),actor_id),
        )
        if status == 'verified':
            self._one("UPDATE geo_placement_submissions SET status='verified' WHERE id=%s::uuid AND project_id=%s::uuid RETURNING *", (submission_id,project_id))
            protocol_rows = self._page(
                """SELECT jsonb_build_object('query_id',id,'query_text',query_text,'platform',platform,'market_code',market_code,
                       'locale',locale,'device',device,'sample_size',sample_size) AS protocol
                   FROM geo_campaign_queries WHERE campaign_id=(SELECT o.campaign_id FROM geo_placement_packages p
                     JOIN geo_placement_opportunities o ON o.id=p.opportunity_id WHERE p.id=(SELECT placement_package_id FROM geo_placement_submissions WHERE id=%s::uuid))
                     AND status='approved' ORDER BY created_at""", (submission_id,)
            )["records"]
            campaign = self._one(
                """SELECT o.campaign_id FROM geo_placement_packages p JOIN geo_placement_opportunities o ON o.id=p.opportunity_id
                   WHERE p.id=(SELECT placement_package_id FROM geo_placement_submissions WHERE id=%s::uuid)""", (submission_id,)
            )
            now = datetime.now(UTC)
            for key, days in (("t28",28),("t56",56),("t84",84)):
                self._one(
                    """INSERT INTO geo_measurement_windows(project_id,campaign_id,submission_id,window_key,due_at,frozen_protocol)
                       VALUES (%s::uuid,%s::uuid,%s::uuid,%s,%s,%s::jsonb) RETURNING *""",
                    (project_id,campaign['campaign_id'],submission_id,key,now + timedelta(days=days),json.dumps(protocol_rows)),
                )
        self._commit()
        return verification

    def submission_verification_target(self, *, project_id: str, submission_id: str) -> dict[str, Any]:
        return self._one(
            """SELECT s.id,s.published_url,s.status,p.rendered_text,p.disclosure_text,d.destination_url
               FROM geo_placement_submissions s
               JOIN geo_placement_packages p ON p.id=s.placement_package_id
               JOIN geo_destinations d ON d.id=s.destination_id
               WHERE s.id=%s::uuid AND s.project_id=%s::uuid""",
            (submission_id, project_id),
        )

    def list_submissions(self, *, project_id: str, campaign_id: str) -> dict[str, Any]:
        return self._page(
            """SELECT s.*,p.title AS package_title,o.campaign_id,d.destination_url FROM geo_placement_submissions s
               JOIN geo_placement_packages p ON p.id=s.placement_package_id JOIN geo_placement_opportunities o ON o.id=p.opportunity_id
               JOIN geo_destinations d ON d.id=s.destination_id WHERE s.project_id=%s::uuid AND o.campaign_id=%s::uuid ORDER BY s.submitted_at DESC""", (project_id,campaign_id)
        )

    def list_measurements(self, *, project_id: str, campaign_id: str) -> dict[str, Any]:
        return self._page(
            """SELECT w.*,m.recommendation_share,m.product_mention_share,m.placement_citation_share,m.verified_placement_coverage,m.calculated_at
               FROM geo_measurement_windows w LEFT JOIN geo_measurements m ON m.measurement_window_id=w.id
               WHERE w.project_id=%s::uuid AND w.campaign_id=%s::uuid ORDER BY w.due_at""", (project_id,campaign_id)
        )

    def customer_summary(self, *, project_id: str) -> dict[str, Any]:
        campaigns = self._page(
            """SELECT c.id,c.name,c.status,p.name AS product_name FROM geo_campaigns_runtime c
               JOIN geo_products p ON p.id=c.product_id WHERE c.project_id=%s::uuid ORDER BY c.created_at""", (project_id,)
        )["records"]
        verified = self._page(
            """SELECT s.id,s.published_url,s.published_at,o.campaign_id,d.name AS destination_name,d.destination_url
               FROM geo_placement_submissions s JOIN geo_placement_packages p ON p.id=s.placement_package_id
               JOIN geo_placement_opportunities o ON o.id=p.opportunity_id JOIN geo_destinations d ON d.id=s.destination_id
               WHERE s.project_id=%s::uuid AND s.status='verified' ORDER BY s.published_at DESC""", (project_id,)
        )["records"]
        windows = self._page(
            """SELECT w.campaign_id,w.window_key,w.due_at,w.status,w.confounded,m.recommendation_share,m.product_mention_share,m.placement_citation_share,m.verified_placement_coverage
               FROM geo_measurement_windows w LEFT JOIN geo_measurements m ON m.measurement_window_id=w.id
               WHERE w.project_id=%s::uuid ORDER BY w.due_at""", (project_id,)
        )["records"]
        return {"campaigns": campaigns, "verified_placements": verified, "measurement_windows": windows}
