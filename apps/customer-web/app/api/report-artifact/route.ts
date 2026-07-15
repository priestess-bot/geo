import { type NextRequest, NextResponse } from "next/server";
import { GEO_SESSION_COOKIE } from "@geo/auth";

import { apiBase } from "../../runtime";

const ARTIFACT_TYPES = new Set(["markdown", "csv", "pdf"]);

export async function GET(request: NextRequest) {
  const reportExportId = request.nextUrl.searchParams.get("report_export_id")?.trim() || "";
  const artifactType = request.nextUrl.searchParams.get("type")?.trim() || "markdown";
  const sessionToken = request.cookies.get(GEO_SESSION_COOKIE)?.value || "";

  if (!reportExportId || !sessionToken) {
    return NextResponse.json({ detail: "An authenticated customer session is required." }, { status: 401 });
  }
  if (!ARTIFACT_TYPES.has(artifactType)) {
    return NextResponse.json({ detail: "Unsupported artifact type." }, { status: 400 });
  }

  const artifactUrl = new URL(`/v1/reports/runtime/${encodeURIComponent(reportExportId)}/artifact`, apiBase());
  artifactUrl.searchParams.set("type", artifactType);
  const artifactResponse = await fetch(artifactUrl.toString(), {
    headers: {
      Cookie: `${GEO_SESSION_COOKIE}=${encodeURIComponent(sessionToken)}`,
      "X-GEO-Customer-Portal-Access": "true"
    },
    cache: "no-store"
  });

  if (!artifactResponse.ok) {
    return new Response(await artifactResponse.text(), {
      status: artifactResponse.status,
      headers: { "Content-Type": artifactResponse.headers.get("content-type") || "text/plain; charset=utf-8" }
    });
  }

  const headers = new Headers();
  for (const key of ["content-type", "content-disposition", "etag", "cache-control"]) {
    const value = artifactResponse.headers.get(key);
    if (value) {
      headers.set(key, value);
    }
  }
  return new Response(artifactResponse.body, { status: artifactResponse.status, headers });
}
