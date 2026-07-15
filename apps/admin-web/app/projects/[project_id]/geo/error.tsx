"use client";

export default function GeoWorkspaceError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return <main className="projectDetailPage"><div className="projectHeader"><div><p className="eyebrow">Admin Web / GEO</p><h1>工作区无法完成加载</h1><p className="muted">{error.message || "发生未预期错误。分区 API 错误会在页面内显示；这里表示页面本身失败。"}</p></div>
    <button className="button" type="button" onClick={reset}>重新加载</button></div>{error.digest ? <div className="panel"><code>Digest {error.digest}</code></div> : null}</main>;
}
