export default function ProjectLoading() {
  return (
    <main className="shell" aria-busy="true" aria-label="项目加载中">
      <section className="topbar compactTopbar">
        <span className="muted">正在加载项目...</span>
      </section>
      <section className="projectHero">
        <p className="eyebrow">项目详情</p>
        <h1>正在读取项目</h1>
        <p className="projectMeta">正在验证权限并加载项目数据。</p>
      </section>
      <section className="workspacePanel" style={{ marginTop: 16, minHeight: 320 }}>
        <p className="muted">加载中...</p>
      </section>
    </main>
  );
}
