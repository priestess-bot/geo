import {
  isCatalogProject,
  nonEmptyString,
  record,
  type CatalogProject,
  type ProjectLoadProblem
} from "../projectTypes";

export const entityTypes = ["brand", "product", "competitor", "market"] as const;
export const subjectRoles = ["primary_brand", "competitor", "market", "product", "neutral"] as const;
export const evidenceItemTypes = [
  "approved_fact",
  "chunk",
  "citation",
  "report_extract",
  "source_asset",
  "consumer_experience"
] as const;
export const genericEvidenceItemTypes = [
  "chunk",
  "citation",
  "report_extract",
  "source_asset",
  "consumer_experience"
] as const;
export const usageRightsValues = [
  "owned",
  "licensed",
  "public_reference",
  "authorised_experience",
  "restricted",
  "unknown"
] as const;
export const confidentialityValues = ["public", "internal", "confidential", "restricted"] as const;

export type EntityType = (typeof entityTypes)[number];
export type SubjectRole = (typeof subjectRoles)[number];
export type EvidenceItemType = (typeof evidenceItemTypes)[number];
export type GenericEvidenceItemType = (typeof genericEvidenceItemTypes)[number];
export type UsageRights = (typeof usageRightsValues)[number];
export type Confidentiality = (typeof confidentialityValues)[number];

export type CatalogEntity = Readonly<{
  id: string;
  project_id: string;
  entity_type: EntityType;
  canonical_name: string;
  canonical_url: string | null;
  attributes: Record<string, unknown>;
  status: string;
  created_at: string;
}>;

export type MarketProfile = Readonly<{
  id: string;
  project_id: string;
  market_code: string;
  locale: string;
  timezone: string;
  rules: Record<string, unknown>;
  status: string;
  created_at: string;
}>;

export type PublicCitation = Readonly<{
  disclosure_allowed: boolean;
  source_url: string | null;
  source_title: string | null;
  label: string | null;
  quotation_allowed: boolean;
  attribution_required: boolean;
}>;

export type EvidenceItem = Readonly<{
  id: string;
  project_id: string;
  item_type: EvidenceItemType;
  source_id: string;
  subject_entity_id: string | null;
  subject_role: SubjectRole;
  locator: Record<string, unknown>;
  snapshot: Readonly<{
    kind: "text" | "minio";
    text: string | null;
    uri: string | null;
    sha256: string;
  }>;
  source_revision: Readonly<{ kind: string; value: string }>;
  usage_rights: UsageRights;
  confidentiality: Confidentiality;
  public_citation: PublicCitation;
  eligible_for_generation: boolean;
  eligible_for_publication: boolean;
  created_at: string;
}>;

export type CatalogResource<T> = Readonly<{
  data: T;
  problem?: ProjectLoadProblem;
}>;

export type CatalogLoadResult = Readonly<{
  project: CatalogResource<CatalogProject | null>;
  entities: CatalogResource<CatalogEntity[]>;
  markets: CatalogResource<MarketProfile[]>;
  evidence: CatalogResource<EvidenceItem[]>;
}>;

export type CatalogActionState = Readonly<{
  kind: "idle" | "success" | "error";
  message?: string;
  status?: number;
  correlationId?: string;
}>;

export type UpdateProjectRequest = Readonly<{
  name?: string;
  status?: "active" | "paused" | "archived";
}>;

export type CreateEntityRequest = Readonly<{
  entity_type: EntityType;
  canonical_name: string;
  canonical_url: string | null;
  attributes: Record<string, unknown>;
}>;

export type CreateMarketProfileRequest = Readonly<{
  market_code: string;
  locale: string;
  timezone: string;
  rules: Record<string, unknown>;
}>;

export type CreateEvidenceRequest = Readonly<{
  item_type: GenericEvidenceItemType;
  source_id: string;
  subject_entity_id: string | null;
  subject_role: SubjectRole;
  locator: Record<string, unknown>;
  snapshot: Readonly<{ kind: "text"; text: string; sha256: string }>;
  source_revision: Readonly<{ kind: "row_version" | "content_hash" | "report_version"; value: string }>;
  usage_rights: UsageRights;
  confidentiality: Confidentiality;
  public_citation: PublicCitation;
}>;

export const initialCatalogActionState: CatalogActionState = { kind: "idle" };

export function isCatalogEntity(value: unknown): value is CatalogEntity {
  if (!record(value)) return false;
  return [value.id, value.project_id, value.canonical_name, value.status, value.created_at].every(nonEmptyString)
    && includes(entityTypes, value.entity_type)
    && (value.canonical_url === null || typeof value.canonical_url === "string")
    && record(value.attributes);
}

export function isMarketProfile(value: unknown): value is MarketProfile {
  if (!record(value)) return false;
  return [
    value.id,
    value.project_id,
    value.market_code,
    value.locale,
    value.timezone,
    value.status,
    value.created_at
  ].every(nonEmptyString) && record(value.rules);
}

export function isEvidenceItem(value: unknown): value is EvidenceItem {
  if (!record(value) || !record(value.snapshot) || !record(value.source_revision)) return false;
  if (!record(value.public_citation) || !record(value.locator)) return false;
  return [
    value.id,
    value.project_id,
    value.source_id,
    value.created_at,
    value.snapshot.sha256,
    value.source_revision.kind,
    value.source_revision.value
  ].every(nonEmptyString)
    && includes(evidenceItemTypes, value.item_type)
    && includes(subjectRoles, value.subject_role)
    && includes(usageRightsValues, value.usage_rights)
    && includes(confidentialityValues, value.confidentiality)
    && (value.subject_entity_id === null || typeof value.subject_entity_id === "string")
    && (value.snapshot.kind === "text" || value.snapshot.kind === "minio")
    && (value.snapshot.text === null || typeof value.snapshot.text === "string")
    && (value.snapshot.uri === null || typeof value.snapshot.uri === "string")
    && typeof value.public_citation.disclosure_allowed === "boolean"
    && typeof value.public_citation.quotation_allowed === "boolean"
    && typeof value.public_citation.attribution_required === "boolean"
    && typeof value.eligible_for_generation === "boolean"
    && typeof value.eligible_for_publication === "boolean";
}

export { isCatalogProject };

function includes<T extends readonly string[]>(values: T, value: unknown): value is T[number] {
  return typeof value === "string" && values.some((candidate) => candidate === value);
}
