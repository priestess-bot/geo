const items = [
  ["已完成", "新增 customer_portal_tokens、project_launch_configs、runtime_http_access_logs 迁移"],
  ["已完成", "客户门户 token 只保存 hash，raw token 仅创建时返回一次"],
  ["已完成", "新增独立 Repository mixin，避免继续堆大 repository.py"],
  ["已完成", "新增独立 API router 与访问日志模块，避免继续堆 main.py"],
  ["进行中", "旧 repository.py、main.py 按域继续拆分"],
  ["进行中", "管理台表单提交与连接测试按钮接入真实 Server Action"],
  ["待做", "旧 apps/web /ops 页面迁移或归档，Compose 不再默认暴露"]
];

export default function DevelopmentBoardPage() {
  return (
    <main className="shell">
      <section className="topbar">
        <div>
          <p className="eyebrow">开发板</p>
          <h1>工程拆分与上线前检查</h1>
          <p className="muted" style={{ marginTop: 8 }}>记录当前架构治理状态，避免后续新增功能继续写进超长文件。</p>
        </div>
        <nav className="nav">
          <a className="button secondary" href="/">返回首页</a>
        </nav>
      </section>

      <section className="grid">
        {items.map(([status, text]) => (
          <div className="projectCard" key={text}>
            <span className="statusPill">{status}</span>
            <h2>{text}</h2>
          </div>
        ))}
      </section>
    </main>
  );
}
