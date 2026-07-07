export default function RetiredDashboardPage() {
  return (
    <main className="retiredShell">
      <section className="retiredPanel">
        <p className="eyebrow">Dashboard retired</p>
        <h1>独立工程看板已合并</h1>
        <p>
          这个 18006 入口不再作为默认服务维护。当前进度、文档索引、审计口径、验收门禁和最近测试产物已经统一合并到
          Admin Web 的 <strong>/development-board</strong>。
        </p>
        <div className="retiredActions">
          <a href="http://localhost:18005/development-board">打开 Development Board</a>
          <a href="http://localhost:18005/projects">打开项目列表</a>
        </div>
      </section>
    </main>
  );
}
