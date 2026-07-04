export default function AdminHome() {
  const entries = [
    {
      href: "/projects/new",
      tone: "homeEntryCreate",
      label: "新建",
      title: "新建 GEO 项目",
      body: "从租户、品牌、市场和竞品开始，完成项目初始化并生成后续配置。",
      action: "开始创建",
      points: ["租户与品牌信息", "市场与竞品设置", "Prompt 初始化"],
      icon: (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M12 5v14M5 12h14" />
        </svg>
      )
    },
    {
      href: "/projects",
      tone: "homeEntryManage",
      label: "管理",
      title: "管理现有项目",
      body: "进入项目列表，维护基础资料、成员权限、启动参数和运行状态。",
      action: "查看项目",
      points: ["项目资料维护", "成员与权限管理", "运行状态跟踪"],
      icon: (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M5 7h14M5 12h14M5 17h9" />
        </svg>
      )
    },
    {
      href: "/development-board",
      tone: "homeEntryDelivery",
      label: "验收",
      title: "开发与验收",
      body: "集中查看交付任务、验证清单和工程风险，处理上线前事项。",
      action: "打开看板",
      points: ["任务拆分", "验证清单", "风险跟踪"],
      icon: (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M6 13l4 4L18 7" />
        </svg>
      )
    }
  ];

  return (
    <main className="shell homeShell">
      <section className="homeHero" aria-labelledby="home-title">
        <div className="homeHeroTitle">
          <h1 id="home-title">GEO 项目管理台</h1>
        </div>
        <nav className="nav homeNav" aria-label="首页快捷入口">
          <a className="button" href="/projects/new">新建项目</a>
          <a className="button secondary" href="/projects">项目列表</a>
          <a className="button secondary" href="/development-board">开发板</a>
        </nav>
      </section>

      <section className="homeEntryGrid" aria-label="主要功能入口">
        {entries.map((entry) => (
          <a className={`homeEntry ${entry.tone}`} href={entry.href} key={entry.href}>
            <span className="homeEntryTop">
              <span className="homeEntryIcon">{entry.icon}</span>
              <span className="homeEntryLabel">{entry.label}</span>
            </span>
            <span className="homeEntryBody">
              <h2>{entry.title}</h2>
              <p>{entry.body}</p>
            </span>
            <ul className="homeEntryMeta">
              {entry.points.map((point) => (
                <li key={point}>{point}</li>
              ))}
            </ul>
            <span className="homeEntryAction">{entry.action}</span>
          </a>
        ))}
      </section>
    </main>
  );
}
