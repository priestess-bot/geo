import { actorHeaders, apiBase } from "../../../../../../runtime";

export async function GET(_request: Request, { params }: { params: Promise<{ project_id: string; version_id: string; export_id: string }> }) {
  const { project_id: projectId, version_id: versionId, export_id: exportId } = await params;
  const url = new URL(`/v1/projects/${encodeURIComponent(projectId)}/geo/package-versions/${encodeURIComponent(versionId)}/exports/${encodeURIComponent(exportId)}/download`, apiBase());
  const upstream = await fetch(url, { headers: await actorHeaders(), cache: "no-store" });
  if (!upstream.ok) {
    const detail = await upstream.text();
    return Response.json({ code: "geo_export_download_failed", detail: detail || "Export download failed" }, { status: upstream.status });
  }
  const headers = new Headers();
  headers.set("Content-Type", upstream.headers.get("content-type") || "application/octet-stream");
  headers.set("Content-Disposition", upstream.headers.get("content-disposition") || `attachment; filename="geo-export-${exportId}.json"`);
  const etag = upstream.headers.get("etag"); if (etag) headers.set("ETag", etag);
  return new Response(upstream.body, { status: 200, headers });
}
