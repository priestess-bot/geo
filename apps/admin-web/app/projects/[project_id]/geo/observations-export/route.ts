import { actorHeaders, apiBase } from "../../../../runtime";

const windows = new Set(["baseline", "t28", "t56", "t84", "ad_hoc"]);

export async function GET(
  request: Request,
  { params }: { params: Promise<{ project_id: string }> }
) {
  const { project_id: projectId } = await params;
  const requestUrl = new URL(request.url);
  const campaignId = requestUrl.searchParams.get("campaign_id")?.trim() || "";
  const protocolId = requestUrl.searchParams.get("protocol_id")?.trim() || "";
  const measurementWindow = requestUrl.searchParams.get("measurement_window")?.trim() || "";
  if (!campaignId || !protocolId || !windows.has(measurementWindow)) {
    return Response.json(
      { code: "geo_observation_export_context_required", detail: "Campaign, protocol and measurement window are required." },
      { status: 422 }
    );
  }
  const upstreamUrl = new URL(
    `/v1/projects/${encodeURIComponent(projectId)}/geo/campaigns/${encodeURIComponent(campaignId)}/monitoring-observations.csv`,
    apiBase()
  );
  upstreamUrl.searchParams.set("protocol_id", protocolId);
  upstreamUrl.searchParams.set("measurement_window", measurementWindow);
  const upstream = await fetch(upstreamUrl, {
    headers: await actorHeaders(),
    cache: "no-store"
  });
  if (!upstream.ok) {
    const detail = await upstream.text();
    return Response.json(
      { code: "geo_observation_export_failed", detail: detail || "Observation export failed" },
      { status: upstream.status }
    );
  }
  const headers = new Headers();
  headers.set("Content-Type", upstream.headers.get("content-type") || "text/csv; charset=utf-8");
  headers.set(
    "Content-Disposition",
    upstream.headers.get("content-disposition")
      || `attachment; filename="geo-observations-${campaignId}-${measurementWindow}.csv"`
  );
  return new Response(upstream.body, { status: 200, headers });
}
