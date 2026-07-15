import CreateProjectForm from "./CreateProjectForm";

export default function NewProjectPage() {
  return (
    <main className="shell">
      <section className="topbar">
        <div>
          <p className="eyebrow">Project Catalog</p>
          <h1>新建项目</h1>
          <p className="muted" style={{ marginTop: 8 }}>
            先创建项目边界，再在项目详情中显式配置实体、市场、证据、成员和客户邀请。
          </p>
        </div>
        <nav className="nav">
          <a className="button secondary" href="/projects">项目列表</a>
          <a className="button secondary" href="/">返回首页</a>
        </nav>
      </section>
      <CreateProjectForm />
    </main>
  );
}
