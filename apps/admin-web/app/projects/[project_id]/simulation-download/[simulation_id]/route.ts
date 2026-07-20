import { actorHeaders, apiBase } from "../../../../runtime";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ project_id: string; simulation_id: string }> }
) {
  const { project_id: projectId, simulation_id: simulationId } = await params;
  const url = new URL(
    `/v1/projects/${encodeURIComponent(projectId)}/geo/prompt-simulations/${encodeURIComponent(simulationId)}/artifact`,
    apiBase()
  );
  const campaignId = new URL(request.url).searchParams.get("campaign_id");
  if (campaignId) url.searchParams.set("campaign_id", campaignId);
  const upstream = await fetch(url, { headers: await actorHeaders(), cache: "no-store" });
  if (!upstream.ok) {
    const detail = await upstream.text();
    return Response.json(
      { code: "geo_prompt_simulation_download_failed", detail: detail || "Prompt simulation download failed" },
      { status: upstream.status }
    );
  }
  const headers = new Headers();
  headers.set("Content-Type", upstream.headers.get("content-type") || "application/json");
  headers.set(
    "Content-Disposition",
    upstream.headers.get("content-disposition") || `attachment; filename="geo-prompt-simulation-${simulationId}.json"`
  );
  for (const header of ["etag", "x-geo-test-only", "x-geo-publication-eligible"]) {
    const value = upstream.headers.get(header);
    if (value) headers.set(header, value);
  }
  return new Response(upstream.body, { status: 200, headers });
}
