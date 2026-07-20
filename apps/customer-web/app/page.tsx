import { redirect } from "next/navigation";

import { InvitationLoginForm } from "./_auth/InvitationLoginForm";
import {
  adminWebBaseUrl,
  loadSessionPortal
} from "./runtime";

// The invite token remains in form memory and is never read from URL state.

export default async function CustomerHome({
  searchParams
}: Readonly<{
  searchParams?: Promise<{ [key: string]: string | string[] | undefined }>;
}>) {
  const params = (await searchParams) || {};
  const invitationId = first(params.invitation_id);
  const requestedProjectId = first(params.project_id);
  const requestedCampaignId = first(params.campaign_id);
  const session = await loadSessionPortal(requestedProjectId);

  if (!session.authenticated) {
    return (
      <main className="shell authShell">
        <section className="authIntro">
          <p className="eyebrow">GEO 客户门户</p>
          <h1>使用客户邀请登录</h1>
          <p>邀请仅用于首次兑换。成功后由安全 Cookie 维持会话，URL 不会继续携带 token。</p>
          {session.problem ? (
            <div aria-live="polite" className="inlineProblem" role="alert">
              <strong>认证服务暂不可用</strong>
              <p>{session.problem.detail}</p>
              {session.problem.request_id ? (
                <p className="muted">请求 ID：{session.problem.request_id}</p>
              ) : null}
            </div>
          ) : null}
          <InvitationLoginForm
            initialInvitationId={invitationId || ""}
            landingPath="/"
            recommendedSurfaceUrls={{ admin: adminWebBaseUrl(), customer: "/" }}
            surface="customer"
          />
        </section>
      </main>
    );
  }

  const query = new URLSearchParams();
  if (requestedProjectId) query.set("project_id", requestedProjectId);
  if (requestedCampaignId) query.set("campaign_id", requestedCampaignId);
  redirect(`/portal/summary${query.size ? `?${query.toString()}` : ""}`);
}

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}
