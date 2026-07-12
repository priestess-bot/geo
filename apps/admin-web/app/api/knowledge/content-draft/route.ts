import { type NextRequest, NextResponse } from "next/server";

import { actorHeaders, apiBase } from "../../../runtime";

export async function GET(request: NextRequest) {
  const projectId = request.nextUrl.searchParams.get("project_id")?.trim() || "";
  const contentDraftId = request.nextUrl.searchParams.get("content_draft_id")?.trim() || "";
  if (!projectId || !contentDraftId) {
    return NextResponse.json({ detail: "project_id and content_draft_id are required" }, { status: 400 });
  }
  const upstreamUrl = new URL(
    `/v1/knowledge/content-drafts/runtime/${encodeURIComponent(contentDraftId)}/export.md`,
    apiBase()
  );
  upstreamUrl.searchParams.set("project_id", projectId);
  const upstream = await fetch(upstreamUrl, {
    method: "POST",
    headers: await actorHeaders(),
    cache: "no-store"
  });
  const body = await upstream.arrayBuffer();
  if (!upstream.ok) {
    const detail = new TextDecoder().decode(body) || "content draft export failed";
    return NextResponse.json({ detail }, { status: upstream.status });
  }
  return new NextResponse(body, {
    status: 200,
    headers: {
      "Content-Type": upstream.headers.get("content-type") || "text/markdown; charset=utf-8",
      "Content-Disposition": upstream.headers.get("content-disposition") || 'attachment; filename="geo-content.md"',
      "Cache-Control": "no-store"
    }
  });
}
