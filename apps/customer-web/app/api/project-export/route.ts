import { apiBase } from "../../runtime";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const projectId = url.searchParams.get("project_id") || "";
  const campaignId = url.searchParams.get("campaign_id") || "";
  if (!projectId || !campaignId) {
    return Response.json({ detail: "project_id and campaign_id are required" }, { status: 422 });
  }
  const upstream = await fetch(
    new URL(
      `/v1/projects/${encodeURIComponent(projectId)}/project-exports/campaigns/${encodeURIComponent(campaignId)}/download`,
      apiBase()
    ),
    { headers: forwardHeaders(request), cache: "no-store" }
  );
  if (!upstream.ok) return proxyJson(upstream);
  const headers = new Headers();
  headers.set("Content-Type", "application/zip");
  headers.set(
    "Content-Disposition",
    upstream.headers.get("content-disposition")
      || `attachment; filename="geo-project-export-${campaignId}.zip"`
  );
  const etag = upstream.headers.get("etag");
  if (etag) headers.set("ETag", etag);
  return new Response(upstream.body, { status: 200, headers });
}

function forwardHeaders(request: Request): Headers {
  const headers = new Headers();
  const cookie = request.headers.get("cookie");
  if (cookie) headers.set("Cookie", cookie);
  return headers;
}

function proxyJson(upstream: Response) {
  return new Response(upstream.body, {
    status: upstream.status,
    headers: { "Content-Type": upstream.headers.get("content-type") || "application/json" }
  });
}
