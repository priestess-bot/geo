export default function ProjectsLoading() {
  return (
    <main className="shell" aria-busy="true" aria-label="项目列表加载中">
      <section className="topbar">
        <div><p className="eyebrow">Project Catalog</p><h1>项目列表</h1></div>
      </section>
      <section className="panel" style={{ marginTop: 18, minHeight: 240 }}>
        <p className="muted">正在读取当前身份获授权的项目...</p>
      </section>
    </main>
  );
}
