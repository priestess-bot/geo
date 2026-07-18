import { type NextRequest, NextResponse } from "next/server";

import { actorHeaders, apiBase } from "../../../runtime";

export async function GET(request: NextRequest) {
  const projectId = request.nextUrl.searchParams.get("project_id")?.trim() || "";
  const sourceId = request.nextUrl.searchParams.get("source_id")?.trim() || "";
  if (!projectId || !sourceId) {
    return NextResponse.json({ detail: "project_id and source_id are required" }, { status: 400 });
  }

  const upstreamUrl = new URL(
    `/v1/projects/${encodeURIComponent(projectId)}/knowledge/sources/${encodeURIComponent(sourceId)}/download`,
    apiBase()
  );
  const upstream = await fetch(upstreamUrl, {
    headers: await actorHeaders(),
    cache: "no-store"
  });
  const body = await upstream.arrayBuffer();
  if (!upstream.ok) {
    const detail = new TextDecoder().decode(body) || "knowledge source asset download failed";
    return NextResponse.json({ detail }, { status: upstream.status });
  }

  return new NextResponse(body, {
    status: 200,
    headers: {
      "Content-Type": upstream.headers.get("content-type") || "application/octet-stream",
      "Content-Disposition": upstream.headers.get("content-disposition") || 'attachment; filename="knowledge-source"',
      "Cache-Control": "private, no-store",
      "X-Content-Type-Options": "nosniff"
    }
  });
}
