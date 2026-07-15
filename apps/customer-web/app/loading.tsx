export default function Loading() {
  return (
    <main aria-busy="true" className="shell" role="status">
      <header className="topbar loadingHeader">
        <div>
          <div className="skeleton short" />
          <div className="skeleton title" />
        </div>
      </header>
      <div className="skeleton nav" />
      <section className="loadingRows">
        <div className="skeleton row" />
        <div className="skeleton row" />
        <div className="skeleton row" />
      </section>
      <span className="srOnly">正在加载客户门户数据</span>
    </main>
  );
}
