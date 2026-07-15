export default function LoadingGeoWorkspace() {
  return <main className="projectDetailPage" aria-busy="true">
    <div className="projectHeader"><div><p className="eyebrow">Admin Web / GEO</p><h1>正在加载 GEO 工作区</h1><p className="muted">正在并行读取 Campaign、渠道、监测与投放 lineage。</p></div></div>
    <div className="panel"><p className="muted">加载稳定运行时资源...</p></div>
  </main>;
}
