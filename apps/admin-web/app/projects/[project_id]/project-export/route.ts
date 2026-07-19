import { actorHeaders, apiBase } from "../../../runtime";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ project_id: string }> }
) {
  const { project_id: projectId } = await params;
  const payload = await request.json().catch(() => ({}));
  const campaignId = typeof payload.campaign_id === "string" && payload.campaign_id
    ? payload.campaign_id
    : null;
  const upstream = await fetch(
    new URL(`/v1/projects/${encodeURIComponent(projectId)}/project-exports`, apiBase()),
    {
      method: "POST",
      headers: await actorHeaders({
        "Content-Type": "application/json",
        "Idempotency-Key": `admin-project-export-${crypto.randomUUID()}`
      }),
      body: JSON.stringify({ campaign_id: campaignId }),
      cache: "no-store"
    }
  );
  return proxyJson(upstream);
}

export async function GET(
  request: Request,
  { params }: { params: Promise<{ project_id: string }> }
) {
  const { project_id: projectId } = await params;
  const jobId = new URL(request.url).searchParams.get("job_id") || "";
  if (!jobId) return Response.json({ detail: "job_id is required" }, { status: 422 });
  const upstream = await fetch(
    new URL(
      `/v1/projects/${encodeURIComponent(projectId)}/project-exports/${encodeURIComponent(jobId)}/download`,
      apiBase()
    ),
    { headers: await actorHeaders(), cache: "no-store" }
  );
  if (!upstream.ok) return proxyJson(upstream);
  return archiveResponse(upstream, jobId);
}

function proxyJson(upstream: Response) {
  return new Response(upstream.body, {
    status: upstream.status,
    headers: { "Content-Type": upstream.headers.get("content-type") || "application/json" }
  });
}

function archiveResponse(upstream: Response, jobId: string) {
  const headers = new Headers();
  headers.set("Content-Type", "application/zip");
  headers.set(
    "Content-Disposition",
    upstream.headers.get("content-disposition")
      || `attachment; filename="geo-project-export-${jobId}.zip"`
  );
  const etag = upstream.headers.get("etag");
  if (etag) headers.set("ETag", etag);
  return new Response(upstream.body, { status: 200, headers });
}
