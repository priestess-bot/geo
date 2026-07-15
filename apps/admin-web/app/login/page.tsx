export default function AdminLoginPage() {
  return (
    <main className="pageShell authPage">
      <section className="detailPanel authPanel">
        <p className="eyebrow">GEO 项目管理台</p>
        <h1>内部用户登录</h1>
        <p className="muted">管理台只接受组织 OIDC 身份。客户一次性邀请请在客户门户兑换。</p>
        <a className="button" href="/api/auth/login">使用组织账号登录</a>
      </section>
    </main>
  );
}
