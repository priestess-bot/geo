import { randomUUID } from "node:crypto";
import { revalidatePath } from "next/cache";
import type { RuntimeHttpResult } from "@geo/api-client/transport";
import type { JsonObject } from "@geo/types/geo";
import { geoClient } from "../../client";

export type ActionResult = { ok?: string; error?: string; status?: number; code?: string; correlationId?: string; retryable?: boolean; nextHref?: string; };
export const initialActionResult: ActionResult = {};
export function value(form: FormData, key: string): string { return String(form.get(key) || "").trim(); }
export function numberValue(form: FormData, key: string, fallback = 0): number { const parsed = Number(value(form, key)); return Number.isFinite(parsed) ? parsed : fallback; }
export function checked(form: FormData, key: string): boolean { return form.get(key) === "on" || form.get(key) === "true"; }
export function lines(form: FormData, key: string): string[] { return value(form, key).split(/\r?\n|,/).map((item) => item.trim()).filter(Boolean); }
export function jsonObject(form: FormData, key: string): JsonObject | ActionResult {
  const raw = value(form, key);
  if (!raw) return {};
  try {
    const parsed = JSON.parse(raw) as unknown;
    return parsed !== null && typeof parsed === "object" && !Array.isArray(parsed)
      ? parsed as JsonObject : { error: `${key} 必须是 JSON 对象`, status: 422, code: "invalid_json_object" };
  } catch { return { error: `${key} 不是有效 JSON`, status: 422, code: "invalid_json" }; }
}
export function jsonArray(form: FormData, key: string): unknown[] | ActionResult {
  const raw = value(form, key);
  try {
    const parsed = JSON.parse(raw) as unknown;
    return Array.isArray(parsed)
      ? parsed : { error: `${key} 必须是 JSON 数组`, status: 422, code: "invalid_json_array" };
  } catch { return { error: `${key} 不是有效 JSON`, status: 422, code: "invalid_json" }; }
}
export function isActionError(value: JsonObject | unknown[] | ActionResult): value is ActionResult { return "error" in value; }
export function guards(form: FormData) { return { idempotencyKey: value(form, "idempotency_key") || randomUUID() }; }
export async function client() { return geoClient(); }
export function finish<T>(projectId: string, result: RuntimeHttpResult<T>, success: string): ActionResult {
  if (result.ok) {
    revalidatePath(`/projects/${projectId}`);
    revalidatePath(`/projects/${projectId}/workflow-c`);
    return { ok: success };
  }
  return { error: result.error.detail, status: result.status, code: result.error.code,
    correlationId: result.error.correlation_id || result.response.correlationId,
    retryable: result.error.retryable === true || !result.status || result.status >= 500 };
}
