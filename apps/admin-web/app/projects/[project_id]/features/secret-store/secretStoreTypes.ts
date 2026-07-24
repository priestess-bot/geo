export type SecretReferenceStatus = "pending" | "active" | "revoked" | "inactive";
export type SecretVersionStatus = "pending" | "active" | "superseded" | "revoked";
export const SECRET_MAX_BYTES = 64 * 1024;
export const SECRET_PURPOSE_GROUPS = [
  {
    label: "模型 Provider",
    options: [
      ["model_provider.openai", "OpenAI API"],
      ["model_provider.deepseek", "DeepSeek API"],
      ["model_provider.kimi", "Kimi API"],
      ["model_provider.gemini", "Gemini API"],
      ["model_provider.perplexity", "Perplexity API"],
      ["model_provider.microsoft", "Microsoft Grounding API"]
    ]
  },
  {
    label: "澳洲采集",
    options: [
      ["egress.proxy.australia", "澳洲出口代理"],
      ["style_collection_login.productreview", "ProductReview 登录"],
      ["style_collection_login.reddit", "Reddit 登录"],
      ["style_collection_login.quora", "Quora 登录"],
      ["style_collection_login.youtube", "YouTube 登录"],
      ["style_collection_login.tiktok", "TikTok 登录"],
      ["style_collection_login.instagram", "Instagram 登录"],
      ["style_collection_login.facebook", "Facebook 登录"],
      ["style_collection_login.linkedin", "LinkedIn 登录"],
      ["style_collection_login.x", "X 登录"]
    ]
  }
] as const;

const SECRET_PURPOSE_KEYS = new Set<string>(
  SECRET_PURPOSE_GROUPS.flatMap((group) => group.options.map(([key]) => key))
);

export function isGovernedSecretPurpose(value: string): boolean {
  return SECRET_PURPOSE_KEYS.has(value);
}

export type SecretReference = Readonly<{
  reference_id: string;
  purpose: string;
  status: SecretReferenceStatus;
  aggregate_version: number;
  current_version: number | null;
  latest_version: number;
  master_key_version: number;
  fingerprint: string;
  created_at: string;
  updated_at: string;
}>;

export type SecretVersionMetadata = Readonly<{
  reference_id: string;
  version: number;
  status: SecretVersionStatus;
  aggregate_version: number;
  master_key_version: number;
  fingerprint: string;
  created_at: string;
  verified_at: string | null;
  activated_at: string | null;
  revoked_at: string | null;
  replayed: boolean;
}>;

export type SecretAuditEvent = Readonly<{
  reference_id: string;
  version: number;
  action: string;
  master_key_version: number;
  fingerprint: string;
  occurred_at: string;
}>;

export type SecretReferencePage = Readonly<{
  items: SecretReference[];
  total: number;
  limit: number;
  offset: number;
}>;

export type SecretAuditPage = Readonly<{
  items: SecretAuditEvent[];
  total: number;
  limit: number;
  offset: number;
}>;

export type SecretLoadProblem = Readonly<{
  status?: number;
  detail: string;
  correlationId?: string;
}>;

export type SecretWorkspaceData = Readonly<{
  references: SecretReferencePage;
  referencesProblem?: SecretLoadProblem;
  audits: SecretAuditPage;
  auditsProblem?: SecretLoadProblem;
  selectionProblem?: SecretLoadProblem;
  selectedReference: SecretReference | null;
}>;

export type SecretActionState = Readonly<{
  kind: "idle" | "success" | "error";
  message?: string;
  status?: number;
  correlationId?: string;
  responseToken?: string;
  nextHref?: string;
  version?: SecretVersionMetadata;
}>;

export const initialSecretActionState: SecretActionState = { kind: "idle" };

const FORBIDDEN_FIELDS = new Set([
  "secret_value",
  "plaintext",
  "ciphertext",
  "data_nonce",
  "wrap_nonce",
  "wrapped_data_key"
]);

export function isSecretReferencePage(value: unknown): value is SecretReferencePage {
  return safeRecord(value)
    && Array.isArray(value.items)
    && value.items.every(isSecretReference)
    && pageNumbers(value);
}

export function isSecretAuditPage(value: unknown): value is SecretAuditPage {
  return safeRecord(value)
    && Array.isArray(value.items)
    && value.items.every(isSecretAuditEvent)
    && pageNumbers(value);
}

export function isSecretReference(value: unknown): value is SecretReference {
  if (!safeRecord(value)) return false;
  return [
    value.reference_id,
    value.purpose,
    value.created_at,
    value.updated_at
  ].every(nonEmptyString)
    && ["pending", "active", "revoked", "inactive"].includes(String(value.status))
    && positiveInteger(value.aggregate_version)
    && (value.current_version === null || positiveInteger(value.current_version))
    && positiveInteger(value.latest_version)
    && positiveInteger(value.master_key_version)
    && isHash(value.fingerprint);
}

export function isSecretVersionMetadata(value: unknown): value is SecretVersionMetadata {
  if (!safeRecord(value)) return false;
  return nonEmptyString(value.reference_id)
    && ["pending", "active", "superseded", "revoked"].includes(String(value.status))
    && positiveInteger(value.version)
    && positiveInteger(value.aggregate_version)
    && positiveInteger(value.master_key_version)
    && isHash(value.fingerprint)
    && nonEmptyString(value.created_at)
    && nullableString(value.verified_at)
    && nullableString(value.activated_at)
    && nullableString(value.revoked_at)
    && typeof value.replayed === "boolean";
}

export function isSecretAuditEvent(value: unknown): value is SecretAuditEvent {
  if (!safeRecord(value)) return false;
  return [value.reference_id, value.action, value.occurred_at].every(nonEmptyString)
    && positiveInteger(value.version)
    && positiveInteger(value.master_key_version)
    && isHash(value.fingerprint);
}

function safeRecord(value: unknown): value is Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  return Object.keys(value).every((key) => !FORBIDDEN_FIELDS.has(key));
}

function pageNumbers(value: Record<string, unknown>): boolean {
  return nonNegativeInteger(value.total)
    && positiveInteger(value.limit)
    && nonNegativeInteger(value.offset);
}

function nullableString(value: unknown): value is string | null {
  return value === null || nonEmptyString(value);
}

function isHash(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
}

function nonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function positiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value > 0;
}

function nonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}
