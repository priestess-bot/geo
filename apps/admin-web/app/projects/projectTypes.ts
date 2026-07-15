export type ProjectRole = "owner" | "admin" | "analyst" | "viewer" | "customer";

export type ProjectSummary = Readonly<{
  id: string;
  key: string;
  name: string;
  role: string;
}>;

export type ProjectListResponse = Readonly<{
  items: ProjectSummary[];
  total: number;
  limit: number;
  offset: number;
}>;

export type CatalogProject = Readonly<{
  id: string;
  tenant_id: string;
  name: string;
  status: "active" | "paused" | "archived";
  created_at: string;
  updated_at: string;
}>;

export type CreateProjectRequest = Readonly<{ name: string }>;

export type ProjectLoadProblem = Readonly<{
  status?: number;
  detail: string;
  correlationId?: string;
}>;

export function isProjectListResponse(value: unknown): value is ProjectListResponse {
  if (!record(value)) return false;
  return Array.isArray(value.items)
    && value.items.every(isProjectSummary)
    && nonNegativeInteger(value.total)
    && positiveInteger(value.limit)
    && nonNegativeInteger(value.offset);
}

export function isCatalogProject(value: unknown): value is CatalogProject {
  if (!record(value)) return false;
  return [
    value.id,
    value.tenant_id,
    value.name,
    value.created_at,
    value.updated_at
  ].every(nonEmptyString)
    && (value.status === "active" || value.status === "paused" || value.status === "archived");
}

function isProjectSummary(value: unknown): value is ProjectSummary {
  if (!record(value)) return false;
  return [value.id, value.key, value.name, value.role].every(nonEmptyString);
}

export function record(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

export function nonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function positiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value > 0;
}

function nonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}
