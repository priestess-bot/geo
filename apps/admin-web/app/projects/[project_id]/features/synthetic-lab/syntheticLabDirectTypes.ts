import type { SyntheticBoundary, SyntheticChannel } from "./syntheticLabTypes";
import {
  hasSyntheticBoundary,
  hasUuidFields,
  isHash,
  isUuid,
  nonEmptyString,
  nullableHash,
  nullableString,
  positiveInteger,
  safeRecord
} from "./syntheticLabTypePrimitives";

export type ChannelStyle = SyntheticBoundary & Readonly<{
  id: string;
  project_id: string;
  style_id: string;
  version_number: number;
  previous_version_id: string | null;
  channel: SyntheticChannel;
  locale: "en-AU";
  directive: string;
  provenance: "manual_initial" | "manual_edit";
  calibration_status: "pending_sample_calibration" | "sample_calibrated";
  style_hash: string;
  replayed: boolean;
}>;

export type DirectKnowledgeItem = Readonly<{
  evidence_id: string;
  kind: "approved_fact" | "citation";
  subject_entity_id: string;
  subject_name: string;
  summary: string;
  snapshot_hash: string;
  source_title: string | null;
  source_url: string | null;
  trace_href: string;
  matched: boolean;
  conflicting: boolean;
}>;

export type DirectGenerationSubject = Readonly<{
  id: string;
  name: string;
  canonical_url: string | null;
  knowledge_snapshot_hash: string | null;
  knowledge_items: DirectKnowledgeItem[];
  competitor_knowledge_snapshot_hash: string | null;
  competitor_knowledge_items: DirectKnowledgeItem[];
}>;

export type DirectGenerationOptions = SyntheticBoundary & Readonly<{
  subjects: DirectGenerationSubject[];
  channel_styles: ChannelStyle[];
  has_competitor_knowledge: boolean;
}>;

export function isChannelStyle(value: unknown): value is ChannelStyle {
  if (!safeRecord(value) || !hasSyntheticBoundary(value)) return false;
  return hasUuidFields(value, ["id", "project_id", "style_id"])
    && positiveInteger(value.version_number)
    && (value.previous_version_id === null || isUuid(value.previous_version_id))
    && isChannel(value.channel)
    && value.locale === "en-AU"
    && nonEmptyString(value.directive)
    && ["manual_initial", "manual_edit"].includes(String(value.provenance))
    && ["pending_sample_calibration", "sample_calibrated"].includes(
      String(value.calibration_status)
    )
    && isHash(value.style_hash)
    && typeof value.replayed === "boolean";
}

export function isDirectGenerationOptions(value: unknown): value is DirectGenerationOptions {
  return safeRecord(value) && hasSyntheticBoundary(value)
    && Array.isArray(value.subjects) && value.subjects.every(isDirectGenerationSubject)
    && Array.isArray(value.channel_styles) && value.channel_styles.every(isChannelStyle)
    && typeof value.has_competitor_knowledge === "boolean";
}

function isDirectGenerationSubject(value: unknown): value is DirectGenerationSubject {
  return safeRecord(value) && isUuid(value.id) && nonEmptyString(value.name)
    && (value.canonical_url === null || nonEmptyString(value.canonical_url))
    && nullableHash(value.knowledge_snapshot_hash)
    && Array.isArray(value.knowledge_items)
    && value.knowledge_items.every(isDirectKnowledgeItem)
    && nullableHash(value.competitor_knowledge_snapshot_hash)
    && Array.isArray(value.competitor_knowledge_items)
    && value.competitor_knowledge_items.every(isDirectKnowledgeItem);
}

function isDirectKnowledgeItem(value: unknown): value is DirectKnowledgeItem {
  return safeRecord(value) && hasUuidFields(value, ["evidence_id", "subject_entity_id"])
    && ["approved_fact", "citation"].includes(String(value.kind))
    && nonEmptyString(value.subject_name)
    && nonEmptyString(value.summary)
    && isHash(value.snapshot_hash)
    && nullableString(value.source_title)
    && nullableString(value.source_url)
    && nonEmptyString(value.trace_href)
    && typeof value.matched === "boolean"
    && typeof value.conflicting === "boolean";
}

function isChannel(value: unknown): value is SyntheticChannel {
  return [
    "owned_site", "amazon", "youtube", "tiktok", "instagram",
    "productreview", "reddit", "ozbargain", "quora"
  ].includes(String(value));
}
