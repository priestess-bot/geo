export default function AdminHome() {
  return (
    <main className="shell">
      <section className="topbar">
        <div>
          <p className="eyebrow">GENO 内部项目中心</p>
          <h1>澳大利亚 GEO 项目管理台</h1>
          <p className="muted" style={{ marginTop: 8 }}>
            面向内部运营与交付人员，按步骤创建项目、配置采集、生成客户门户 token，并复盘审计证据。
          </p>
        </div>
        <nav className="nav">
          <a className="button" href="/projects/new">新建项目</a>
          <a className="button secondary" href="/projects">项目列表</a>
          <a className="button secondary" href="/development-board">开发板</a>
        </nav>
      </section>

      <section className="stats">
        <div className="stat"><span className="muted">创建流程</span><strong>5 步</strong></div>
        <div className="stat"><span className="muted">客户入口</span><strong>单项目</strong></div>
        <div className="stat"><span className="muted">审计策略</span><strong>全链路</strong></div>
        <div className="stat"><span className="muted">旧 /ops</span><strong>不暴露</strong></div>
      </section>

      <section className="grid">
        <a className="projectCard" href="/projects/new">
          <span className="statusPill">Step-by-step</span>
          <h2>创建澳大利亚 GEO 项目</h2>
          <p className="muted">录入租户、品牌、主域名、竞品、客户邮箱、采集模式和外部连接器。</p>
        </a>
        <a className="projectCard" href="/projects">
          <span className="statusPill">管理</span>
          <h2>项目配置与成员</h2>
          <p className="muted">查看项目、启动配置、成员邀请、门户 token 和评分/品牌默认设置。</p>
        </a>
        <a className="projectCard" href="/development-board">
          <span className="statusPill">工程</span>
          <h2>开发板与审计</h2>
          <p className="muted">跟踪当前拆分计划、超长文件治理和上线前验证项。</p>
        </a>
      </section>
    </main>
  );
}
