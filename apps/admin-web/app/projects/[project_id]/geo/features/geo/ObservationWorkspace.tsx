import Link from "next/link";
import { ActionForm } from "./ActionForm";
import { importObservation } from "./campaign-actions";
import { Empty, HiddenProject, ResourceBlock, SectionHeader, ShortId, Status, geoHref } from "./common";
import type { GeoWorkspaceData } from "./model";
import styles from "./GeoWorkspace.module.css";

const windows = ["baseline", "t28", "t56", "t84", "ad_hoc"] as const;

export function ObservationWorkspace({ projectId, data }: { projectId: string; data: GeoWorkspaceData }) {
  const { selection } = data;
  const protocol = data.protocols.data.find((item) => item.id === selection.protocolId);
  const canImport = protocol?.status === "frozen";
  return <section className={styles.workspace}>
    <SectionHeader eyebrow="Raw evidence" title="AI 搜索观察样本与公开引用">
      <div className={styles.toolbar}>{windows.map((window) => <Link className={selection.measurementWindow === window ? "button" : "button secondary"} key={window}
        href={geoHref(projectId, selection, { measurement_window: window })}>{window}</Link>)}</div>
    </SectionHeader>
    <div className={styles.split}>
      <aside className={`${styles.workspace} ${styles.sticky}`}>
        <div className={styles.panel}><h3>监测协议</h3><ResourceBlock resource={data.protocols}>{(protocols) => protocols.length ? <div className={styles.list}>{protocols.map((item) => <Link
          className={item.id === selection.protocolId ? styles.selectedRow : styles.row} key={item.id}
          href={geoHref(projectId, selection, { protocol_id: item.id, campaign_id: item.campaign_id })}>
          <span className={styles.rowHeader}><strong>{item.name}</strong><Status value={item.status} /></span>
          <span className={styles.meta}><span>{item.platform}</span><span>{item.locale}</span><span>{item.sample_size} samples</span></span>
        </Link>)}</div> : <Empty>先建立监测协议。</Empty>}</ResourceBlock></div>
        <div className={styles.panel}>
          <ActionForm action={importObservation} title="导入人工观察" submitLabel="保存原始样本" disabled={!canImport || data.queries.data.length === 0}>
            <HiddenProject projectId={projectId} /><input type="hidden" name="protocol_id" value={protocol?.id || ""} />
            <input type="hidden" name="measurement_window" value={selection.measurementWindow} />
            <label>监测查询<select name="monitoring_query_id" required defaultValue=""><option value="" disabled>选择查询</option>{data.queries.data.map((query) => <option value={query.id} key={query.id}>{query.query_text}</option>)}</select></label>
            <div className={styles.inline}><label>样本编号<input name="sample_index" type="number" min="1" defaultValue="1" required /></label><label>结果<select name="result_status" defaultValue="succeeded"><option value="succeeded">成功</option><option value="failed">失败</option></select></label></div>
            <label>观测时间<input name="observed_at" type="datetime-local" required /></label>
            <label>配置模型<input name="configured_model" defaultValue="deepseek-chat" required /></label><label>提供方报告模型<input name="provider_reported_model" /></label>
            <label>界面/入口<input name="ui_surface" defaultValue="manual browser session" required /></label>
            <label>原始回答<textarea name="raw_answer" placeholder="完整保存 AI 搜索回答" /></label>
            <label>引用 URL<textarea name="citation_urls" placeholder="每行一条，系统保留逐条验证状态" /></label>
            <label>截图/导出工件 URI<input name="artifact_uri" type="url" /></label>
            <div className={styles.inline}><label className={styles.check}><input type="checkbox" name="eligible" defaultChecked />样本符合协议</label><label>URL 检查<select name="url_verification_status" defaultValue="unknown"><option value="unknown">未检查</option><option value="passed">通过</option><option value="failed">失败</option></select></label></div>
            <label className={styles.check}><input type="checkbox" name="recommendation_present" />出现推荐</label>
            <label className={styles.check}><input type="checkbox" name="primary_product_mentioned" />出现主商品</label>
            <label className={styles.check}><input type="checkbox" name="competitor_mentioned" />出现竞品</label>
            <label>混杂因素<textarea name="confounding_factors" placeholder="每行一条" /></label><label>不合格原因<textarea name="ineligible_reasons" placeholder="每行一条" /></label>
          </ActionForm>
          {!canImport ? <p className={styles.meta}>只有冻结的协议可接收观察样本，避免测量口径漂移。</p> : null}
        </div>
      </aside>
      <div className={styles.workspace}>
        <div className={styles.summary}>
          <div className={styles.metric}><span>窗口</span><strong>{selection.measurementWindow}</strong></div>
          <div className={styles.metric}><span>总样本</span><strong>{data.observations.data.length}</strong></div>
          <div className={styles.metric}><span>合格</span><strong>{data.observations.data.filter((item) => item.eligible).length}</strong></div>
          <div className={styles.metric}><span>主商品提及</span><strong>{data.observations.data.filter((item) => item.primary_product_mentioned).length}</strong></div>
          <div className={styles.metric}><span>已验证引用</span><strong>{data.observations.data.flatMap((item) => item.citations).filter((item) => item.verification_status === "passed").length}</strong></div>
        </div>
        <ResourceBlock resource={data.observations}>{(observations) => observations.length ? observations.map((observation) => <article className={styles.panel} key={observation.id}>
          <div className={styles.rowHeader}><div><strong>样本 #{observation.sample_index}</strong> <ShortId value={observation.id} /></div><Status value={observation.eligible ? "eligible" : "ineligible"} /></div>
          <div className={styles.keyValues}>
            <div><span className={styles.meta}>模型</span><br /><strong>{observation.provider_reported_model || observation.configured_model}</strong></div>
            <div><span className={styles.meta}>观测时间</span><br /><strong>{new Date(observation.observed_at).toLocaleString("zh-CN")}</strong></div>
            <div><span className={styles.meta}>结果 / URL</span><br /><strong>{observation.result_status} / {observation.url_verification_status}</strong></div>
          </div>
          <pre className={styles.answer}>{observation.raw_answer || "未提供文本回答；请查阅关联工件。"}</pre>
          <h3>公开引用</h3>
          {observation.citations.length ? observation.citations.map((citation) => <div className={styles.citation} key={citation.id}>
            <a href={citation.url} target="_blank" rel="noreferrer">{citation.title || citation.url}</a><Status value={citation.verification_status} />
            <span className={styles.meta}>{citation.verified_placement ? "已关联验证投放" : "未关联验证投放"}</span>
          </div>) : <Empty>这个样本没有公开引用。</Empty>}
          <div className={styles.meta}><span>payload {observation.payload_hash.slice(0, 12)}</span><span>{observation.artifact_uri || "无外部工件"}</span>{observation.replayed ? <span>幂等重放</span> : null}</div>
        </article>) : <Empty>当前协议和窗口尚无观察样本。</Empty>}</ResourceBlock>
      </div>
    </div>
  </section>;
}
