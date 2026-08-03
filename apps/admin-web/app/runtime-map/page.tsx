export default function RuntimeMapPage() {
  return (
    <main className="runtimeMapShell">
      <header className="runtimeMapTopbar">
        <div>
          <p className="eyebrow">全局运行视图</p>
          <h1>运行地图</h1>
        </div>
        <nav className="nav" aria-label="运行地图导航">
          <a className="button secondary" href="/projects">项目列表</a>
          <a className="button secondary" href="/">返回首页</a>
        </nav>
      </header>
      <iframe
        className="runtimeMapFrame"
        loading="eager"
        sandbox="allow-scripts allow-top-navigation-by-user-activation"
        src="/runtime-map/document"
        title="GEO 项目运行地图"
      />
    </main>
  );
}
