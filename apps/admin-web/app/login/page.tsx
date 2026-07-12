export default async function AdminLoginPage({
  searchParams
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = (await searchParams) || {};
  const errorValue = Array.isArray(params.error) ? params.error[0] : params.error;
  return (
    <main className="pageShell authPage">
      <section className="detailPanel authPanel">
        <p className="eyebrow">GEO 项目管理台</p>
        <h1>内部用户登录</h1>
        <p className="muted">使用管理员邀请完成首次登录；已有 bootstrap session 时可直接建立本机安全会话。</p>
        {errorValue ? <p className="notice errorText">{errorValue}</p> : null}
        <form className="configForm singleColumn" method="post" action="/api/auth/login">
          <label>
            <span>邀请 ID</span>
            <input name="invitation_id" autoComplete="off" />
          </label>
          <label>
            <span>一次性邀请 token</span>
            <input name="invite_token" type="password" autoComplete="one-time-code" />
          </label>
          <div className="formActions"><button type="submit">兑换邀请并登录</button></div>
        </form>
        <details className="detailPanel compactForm">
          <summary>使用初始化 session</summary>
          <form className="configForm singleColumn" method="post" action="/api/auth/login">
            <label>
              <span>Bootstrap session token</span>
              <input name="session_token" type="password" autoComplete="off" required />
            </label>
            <div className="formActions"><button type="submit">建立管理会话</button></div>
          </form>
        </details>
      </section>
    </main>
  );
}
