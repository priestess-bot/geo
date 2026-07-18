import { ActionForm } from "./ActionForm";
import { importObservation } from "./campaign-actions";
import { CommandPanel, Empty, geoHref, HiddenProject, ResourceBlock, Status, TechnicalInfo } from "./common";
import type { GeoWorkspaceData } from "./model";
import styles from "./GeoWorkspace.module.css";

const windows = [["baseline", "基线"], ["t28", "T+28"], ["t56", "T+56"], ["t84", "T+84"], ["ad_hoc", "临时测量"]] as const;

export function ObservationWorkspace({ projectId, data }: { projectId: string; data: GeoWorkspaceData }) {
  const { selection } = data;
  const protocol = data.protocols.data.find((item) => item.id === selection.protocolId);
  const canImport = protocol?.status === "frozen";
  const eligible = data.observations.data.filter((item) => item.eligible).length;
  return <section className={styles.workspace}>
    <header className={styles.pageHeading}><div><h2>AI 搜索观察</h2><p>使用冻结的监测方案记录回答、推荐结果和公开引用。</p></div>
      <CommandPanel label="录入观察样本"><ObservationForm projectId={projectId} data={data} canImport={canImport} protocolId={protocol?.id} /></CommandPanel>
    </header>
    <nav className={styles.tabs} aria-label="测量窗口">{windows.map(([value, label]) => <a className={selection.measurementWindow === value ? styles.active : ""} key={value} href={geoHref(projectId, selection, { measurement_window: value })}>{label}</a>)}</nav>
    <div className={styles.summary}>
      <div className={styles.metric}><span>当前方案</span><strong>{protocol?.name || "未选择"}</strong></div>
      <div className={styles.metric}><span>总样本</span><strong>{data.observations.data.length}</strong></div>
      <div className={styles.metric}><span>合格样本</span><strong>{eligible}</strong></div>
      <div className={styles.metric}><span>产品被提及</span><strong>{data.observations.data.filter((item) => item.primary_product_mentioned).length}</strong></div>
      <div className={styles.metric}><span>引用投放页面</span><strong>{data.observations.data.flatMap((item) => item.citations).filter((item) => item.verified_placement).length}</strong></div>
    </div>
    {!protocol ? <div className={styles.notice}><span>当前 Campaign 尚未建立监测方案。</span><a href={geoHref(projectId, selection, { section: "campaigns" })}>前往建立方案</a></div> : null}
    {protocol && !canImport ? <div className={styles.notice}><span>方案需要批准并冻结后才能录入观察，确保前后测量口径一致。</span><a href={geoHref(projectId, selection, { section: "campaigns" })}>查看监测方案</a></div> : null}
    <ResourceBlock resource={data.observations}>{(observations) => observations.length ? <div className={styles.workspace}>{observations.map((observation) => <article className={styles.panel} key={observation.id}>
      <div className={styles.rowHeader}><div><strong>样本 #{observation.sample_index}</strong><span className={styles.meta}>{new Date(observation.observed_at).toLocaleString("zh-CN")}</span></div><Status value={observation.eligible ? "qualified" : "blocked"} /></div>
      <div className={styles.keyValues}><div><span className={styles.meta}>模型</span><br /><strong>{observation.provider_reported_model || observation.configured_model}</strong></div><div><span className={styles.meta}>推荐结果</span><br /><strong>{observation.recommendation_present ? "出现产品推荐" : "未出现推荐"}</strong></div><div><span className={styles.meta}>引用检查</span><br /><strong>{observation.citations.length} 个公开来源</strong></div></div>
      <pre className={styles.answer}>{observation.raw_answer || "未保存文本回答，请查看关联工件。"}</pre>
      {observation.citations.length ? <div>{observation.citations.map((citation) => <div className={styles.citation} key={citation.id}><a href={citation.url} target="_blank" rel="noreferrer">{citation.title || citation.url}</a><Status value={citation.verification_status} /><span className={styles.meta}>{citation.verified_placement ? "已关联已验证投放" : "普通公开引用"}</span></div>)}</div> : <Empty>这个样本没有公开引用。</Empty>}
      <TechnicalInfo><code>Observation {observation.id}</code><code>Payload {observation.payload_hash}</code><span>{observation.artifact_uri || "无外部工件"}</span></TechnicalInfo>
    </article>)}</div> : <Empty>当前监测方案和窗口还没有观察样本。冻结方案后录入第一条基线结果。</Empty>}</ResourceBlock>
  </section>;
}

function ObservationForm({ projectId, data, canImport, protocolId }: { projectId: string; data: GeoWorkspaceData; canImport: boolean; protocolId?: string }) {
  return <ActionForm action={importObservation} submitLabel="保存观察样本" disabled={!canImport || data.protocolQueries.data.length === 0}>
    <HiddenProject projectId={projectId} /><input type="hidden" name="protocol_id" value={protocolId || ""} /><input type="hidden" name="measurement_window" value={data.selection.measurementWindow} />
    <label>消费者问题<select name="monitoring_query_id" required defaultValue=""><option value="" disabled>选择方案中的问题</option>{data.protocolQueries.data.map((query) => <option value={query.monitoring_query_id} key={query.id}>{query.ordinal}. {query.query_text}</option>)}</select></label>
    <div className={styles.inline}><label>样本编号<input name="sample_index" type="number" min="1" defaultValue="1" required /></label><label>采集结果<select name="result_status" defaultValue="succeeded"><option value="succeeded">成功</option><option value="failed">失败</option></select></label></div>
    <label>观察时间<input name="observed_at" type="datetime-local" required /></label>
    <label>AI 回答<textarea name="raw_answer" placeholder="完整保存本次 AI 搜索回答" /></label>
    <label>已验证投放引用<select name="verified_citation_targets" multiple size={Math.min(5, Math.max(2, data.citationTargets.data.length))}>{data.citationTargets.data.map((target) => <option value={JSON.stringify({ url: target.url, submission_id: target.submission_id })} key={target.submission_id}>{target.publication_channel} · {target.destination_key}</option>)}</select></label>
    <label>其他公开引用网址<textarea name="citation_urls" placeholder="每行一个网址" /></label>
    <div className={styles.inline}><label className={styles.check}><input type="checkbox" name="eligible" defaultChecked />符合监测方案</label><label>网址检查<select name="url_verification_status" defaultValue="unknown"><option value="unknown">未检查</option><option value="passed">通过</option><option value="failed">失败</option></select></label></div>
    <label className={styles.check}><input type="checkbox" name="recommendation_present" />回答中出现产品推荐</label><label className={styles.check}><input type="checkbox" name="primary_product_mentioned" />回答中出现主产品</label><label className={styles.check}><input type="checkbox" name="competitor_mentioned" />回答中出现竞品</label>
    <label>影响结果的其他因素<textarea name="confounding_factors" placeholder="每行一项" /></label><label>样本不合格原因<textarea name="ineligible_reasons" placeholder="仅在不合格时填写" /></label>
    <details><summary>技术采集信息</summary><div className={styles.formInset}><label>配置模型<input name="configured_model" defaultValue="deepseek-chat" required /></label><label>平台报告模型<input name="provider_reported_model" /></label><label>采集入口<input name="ui_surface" defaultValue="manual browser session" required /></label><label>截图或导出工件 URL<input name="artifact_uri" type="url" /></label></div></details>
  </ActionForm>;
}
