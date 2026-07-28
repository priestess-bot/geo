const HASH_PATTERN = /^[0-9a-f]{64}$/;
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const FORBIDDEN_FIELDS = new Set([
  "authorization",
  "authorization_header",
  "authorization_value",
  "cookie",
  "cookies",
  "credential",
  "credentials",
  "debug_trace",
  "model_response",
  "password",
  "plaintext",
  "raw_text",
  "secret",
  "secret_value",
  "session_token",
  "storage_state"
]);

export function safeRecord(value: unknown): value is Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  return Object.keys(value).every((key) => !FORBIDDEN_FIELDS.has(key.toLowerCase()));
}

export function hasSyntheticBoundary(value: Record<string, unknown>): boolean {
  return value.synthetic === true
    && value.test_only === true
    && value.publication_eligible === false;
}

export function hasUuidFields(value: Record<string, unknown>, names: string[]): boolean {
  return names.every((name) => typeof value[name] === "string" && UUID_PATTERN.test(value[name]));
}

export function stringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(nonEmptyString);
}

export function isHash(value: unknown): value is string {
  return typeof value === "string" && HASH_PATTERN.test(value);
}

export function nullableHash(value: unknown): boolean {
  return value === null || isHash(value);
}

export function nullableString(value: unknown): boolean {
  return value === null || nonEmptyString(value);
}

export function nonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

export function positiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value > 0;
}

export function nullablePositiveInteger(value: unknown): boolean {
  return value === null || positiveInteger(value);
}

export function nonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}
