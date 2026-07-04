import { type NextRequest, NextResponse } from "next/server";

import { apiBase } from "../../runtime";

const ARTIFACT_TYPES = new Set(["markdown", "csv", "pdf"]);

type PortalAccessResponse = {
  bundle?: { access?: { member_user_id?: string } };
};

export async function GET(request: NextRequest) {
  const reportExportId = request.nextUrl.searchParams.get("report_export_id")?.trim() || "";
  const artifactType = request.nextUrl.searchParams.get("type")?.trim() || "markdown";
  const portalToken = request.nextUrl.searchParams.get("portal_token")?.trim() || "";

  if (!reportExportId || !portalToken) {
    return NextResponse.json({ detail: "report_export_id and portal_token are required." }, { status: 400 });
  }
  if (!ARTIFACT_TYPES.has(artifactType)) {
    return NextResponse.json({ detail: "Unsupported artifact type." }, { status: 400 });
  }

  const accessResponse = await fetch(new URL("/v1/customer-portal/access", apiBase()).toString(), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ portal_token: portalToken }),
    cache: "no-store"
  });
  if (!accessResponse.ok) {
    return NextResponse.json({ detail: "Portal token is invalid or expired." }, { status: accessResponse.status });
  }

  const access = (await accessResponse.json()) as PortalAccessResponse;
  const actorId = access.bundle?.access?.member_user_id;
  if (!actorId) {
    return NextResponse.json({ detail: "Portal access is missing member_user_id." }, { status: 403 });
  }

  const artifactUrl = new URL(`/v1/reports/runtime/${encodeURIComponent(reportExportId)}/artifact`, apiBase());
  artifactUrl.searchParams.set("type", artifactType);
  const artifactResponse = await fetch(artifactUrl.toString(), {
    headers: {
      "X-GENO-Actor-Id": actorId,
      "X-GENO-Customer-Portal-Access": "true"
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
