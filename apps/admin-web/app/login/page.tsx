import { InvitationLoginForm } from "../_auth/InvitationLoginForm";
import { customerWebBaseUrl } from "../runtime";

export default async function AdminLoginPage({
  searchParams
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = (await searchParams) || {};
  const invitationId = Array.isArray(params.invitation_id) ? params.invitation_id[0] : params.invitation_id;
  return (
    <main className="pageShell authPage">
      <section className="detailPanel authPanel">
        <p className="eyebrow">GEO 项目管理台</p>
        <h1>内部用户登录</h1>
        <p className="muted">使用管理台邀请完成登录。</p>
        {invitationId ? (
          <p className="muted">请输入邮件中单独提供的一次性邀请 code；如未收到，请联系管理员重发邀请。</p>
        ) : null}
        <InvitationLoginForm
          initialInvitationId={invitationId || ""}
          landingPath="/projects"
          recommendedSurfaceUrls={{ admin: "/login", customer: customerWebBaseUrl() }}
          surface="admin"
        />
      </section>
    </main>
  );
}
