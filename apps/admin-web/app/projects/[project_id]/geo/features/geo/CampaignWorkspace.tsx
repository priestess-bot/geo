import { ActionForm } from "./ActionForm";
import { approveReport, approveSuggestion, changeProtocol, computeMetrics, createCampaign, createMonitoringQuery, createProtocol, createReport, createSuggestion } from "./campaign-actions";
import { CommandPanel, Empty, geoHref, HiddenProject, ResourceBlock, Status, TechnicalInfo } from "./common";
import { entityName, marketName } from "./display";
import type { GeoWorkspaceData } from "./model";
import type { CatalogLoadResult } from "../../../catalogTypes";
import styles from "./GeoWorkspace.module.css";
import { ProtocolSourceStratumFields } from "./ObservationSourceFields";
import { MonitoringMetricSnapshot } from "./MonitoringMetricSnapshot";
import { sourceStratumHash, sourceStratumLabel } from "./monitoring-statistics";
import { ProtocolSamplingFields } from "./ProtocolSamplingFields";
import { QuestionSetWorkspace } from "./QuestionSetWorkspace";

export function CampaignWorkspace({ projectId, data, catalog }: {
  projectId: string; data: GeoWorkspaceData; catalog: CatalogLoadResult;
}) {
  const { selection } = data;
  const selectedCampaign = data.campaigns.data.find((item) => item.id === selection.campaignId);
  const selectedProtocol = data.protocols.data.find((item) => item.id === selection.protocolId);
  const products = catalog.entities.data.filter((item) => item.entity_type === "product");
  const market = catalog.markets.data.find((item) => item.id === selectedCampaign?.market_profile_id);
  const sourceStrata = (selectedProtocol?.source_strata || []).map((stratum) => ({
    hash: sourceStratumHash(stratum),
    label: sourceStratumLabel(stratum)
  }));
  const queryClusters = Array.from(new Set(data.protocolQueries.data
    .map((item) => item.query_cluster_key)
    .filter((item): item is string => Boolean(item))));
  return <section className={styles.workspace}>
    <header className={styles.pageHeading}>
      <div><h2>活动总览</h2><p>围绕一个产品维护消费者问题、固定监测口径并查看阶段性结果。</p></div>
      <CommandPanel label="新建活动">
        <ActionForm action={createCampaign} submitLabel="创建并建立渠道任务" disabled={data.destinations.data.length === 0}>
          <HiddenProject projectId={projectId} />
          <label>活动名称<input name="name" required placeholder="例如：V600 澳大利亚推荐覆盖" /></label>
          <label>市场<select name="market_profile_id" required defaultValue={catalog.markets.data[0]?.id || ""}>{catalog.markets.data.map((item) => <option key={item.id} value={item.id}>{marketName(catalog.markets.data, item.id)}</option>)}</select></label>
          <label>主产品<select name="primary_product_entity_id" required defaultValue={products[0]?.id || ""}>{products.map((item) => <option key={item.id} value={item.id}>{item.canonical_name}</option>)}</select></label>
          <label>目标渠道<select name="destination_ids" required multiple size={Math.min(6, Math.max(3, data.destinations.data.length))}>{data.destinations.data.map((item) => <option key={item.id} value={item.id}>{item.destination_key}</option>)}</select></label>
          <label>业务目标<select name="objective" defaultValue="recommendation_influence"><option value="recommendation_influence">提升 AI 推荐与引用覆盖</option></select></label>
          <label>选择渠道的原因<textarea name="opportunity_rationale" required placeholder="说明产品、消费者问题与这些渠道之间的关系" /></label>
        </ActionForm>
      </CommandPanel>
    </header>

    <section className={styles.panel}>
      <h3>产品活动</h3>
      <table className={styles.table}><thead><tr><th>活动</th><th>产品</th><th>市场</th><th>状态</th></tr></thead><tbody>
        {data.campaigns.data.map((item) => <tr key={item.id}><td><a href={geoHref(projectId, selection, {
          campaign_id: item.id, protocol_id: undefined, destination_id: undefined,
          opportunity_id: undefined, brief_version_id: undefined, attempt_id: undefined,
          skill_id: undefined, bundle_id: undefined, job_id: undefined, version_id: undefined,
          publication_id: undefined, submission_id: undefined, simulation_id: undefined,
          question_generation_job_id: undefined,
          placement_stage: "brief", measurement_window: "baseline"
        })}><strong>{item.name}</strong></a><TechnicalInfo><code>{item.id}</code></TechnicalInfo></td>
          <td>{entityName(catalog.entities.data, item.primary_product_entity_id)}</td><td>{marketName(catalog.markets.data, item.market_profile_id)}</td><td><Status value={item.status} /></td></tr>)}
      </tbody></table>
    </section>

    <div className={styles.columns}>
      <section className={styles.panel}>
        <div className={styles.sectionHeader}><div><p>消费者需求</p><h2>消费者问题</h2></div><span className={styles.meta}>{data.queries.data.length} 条</span></div>
        <ResourceBlock resource={data.queries}>{(queries) => queries.length ? <table className={styles.table}><thead><tr><th>问题</th><th>意图</th><th>状态</th></tr></thead><tbody>{queries.map((query) => <tr key={query.id}><td><strong>{query.query_text}</strong></td><td>{queryKindLabel(query.query_kind)} · {query.locale}</td><td><Status value={query.status} /></td></tr>)}</tbody></table> : <Empty>还没有消费者问题。先添加真实购买或比较场景中的问法。</Empty>}</ResourceBlock>
        <CommandPanel label="添加消费者问题"><ActionForm action={createMonitoringQuery} submitLabel="添加问题" disabled={!selectedCampaign}>
          <HiddenProject projectId={projectId} /><input type="hidden" name="campaign_id" value={selectedCampaign?.id || ""} /><input type="hidden" name="market_profile_id" value={selectedCampaign?.market_profile_id || ""} />
          <label>消费者问题<textarea name="query_text" required placeholder="例如：600 平方米草坪适合考虑哪款机器人割草机？" /></label>
          <div className={styles.inline}><label>意图<select name="query_kind" defaultValue="recommendation"><option value="recommendation">商品推荐</option><option value="comparison">产品比较</option><option value="research">购买调研</option><option value="support">使用支持</option></select></label>
            <label>语言<input name="locale" defaultValue={market?.locale || "en-AU"} required /></label></div>
        </ActionForm></CommandPanel>
      </section>

      <section className={styles.panel}>
        <div className={styles.sectionHeader}><div><p>固定测量口径</p><h2>监测方案</h2></div>{selectedProtocol ? <Status value={selectedProtocol.status} /> : null}</div>
        <ResourceBlock resource={data.protocols}>{(protocols) => protocols.length ? <div className={styles.list}>{protocols.map((protocol) => <a href={geoHref(projectId, selection, { protocol_id: protocol.id })} className={protocol.id === selection.protocolId ? styles.selectedRow : styles.row} key={protocol.id}>
          <span className={styles.rowHeader}><strong>{protocol.name}</strong><Status value={protocol.status} /></span><span className={styles.meta}>{platformLabel(protocol.platform)} · {protocol.locale} · {deviceLabel(protocol.device)} · 每个问题 {protocol.sample_size} 次 · 有效门槛 {protocol.minimum_valid_repeats ?? "legacy"}</span></a>)}</div> : <Empty>建立监测方案后，才能录入基线并在后续窗口使用相同口径复测。</Empty>}</ResourceBlock>
        <CommandPanel label="新建监测方案"><ActionForm action={createProtocol} submitLabel="保存方案" disabled={!selectedCampaign}>
          <HiddenProject projectId={projectId} /><input type="hidden" name="campaign_id" value={selectedCampaign?.id || ""} /><input type="hidden" name="market_profile_id" value={selectedCampaign?.market_profile_id || ""} />
          <label>方案名称<input name="name" required placeholder="例如：ChatGPT AU 基线" /></label>
          <ProtocolSourceStratumFields locale={market?.locale || "en-AU"} />
          <ProtocolSamplingFields />
          <label>测量窗口（天）<input name="window_days" type="number" min="1" max="365" defaultValue="28" required /></label>
        </ActionForm></CommandPanel>
        {selectedProtocol ? <div className={styles.toolbar}>{selectedProtocol.status === "draft" ? <ActionForm action={changeProtocol} submitLabel="批准方案"><HiddenProject projectId={projectId} /><input type="hidden" name="campaign_id" value={selection.campaignId || ""} /><input type="hidden" name="protocol_id" value={selectedProtocol.id} /><input type="hidden" name="command" value="approve" /></ActionForm> : null}
          {selectedProtocol.status === "approved" ? <ActionForm action={changeProtocol} submitLabel="冻结测量口径"><HiddenProject projectId={projectId} /><input type="hidden" name="campaign_id" value={selection.campaignId || ""} /><input type="hidden" name="protocol_id" value={selectedProtocol.id} /><input type="hidden" name="command" value="freeze" /></ActionForm> : null}</div> : null}
      </section>
    </div>

    {selectedCampaign ? <QuestionSetWorkspace data={data} projectId={projectId} /> : null}

    <CommandPanel label="高级运营：查询建议、指标与客户报告">
      <div className={styles.columns}>
        <section className={styles.unframed}><h3>查询建议</h3><ActionForm action={createSuggestion} submitLabel="提交建议" disabled={!selectedProtocol}>
          <HiddenProject projectId={projectId} /><input type="hidden" name="campaign_id" value={selection.campaignId || ""} /><input type="hidden" name="protocol_id" value={selectedProtocol?.id || ""} /><label>建议问法<textarea name="query_text" required /></label><label>问题簇<input name="query_cluster_key" required placeholder="例如：product-comparison" /></label><label>建议依据<textarea name="rationale" required /></label><label>类型<select name="query_kind" defaultValue="recommendation"><option value="recommendation">商品推荐</option><option value="comparison">产品比较</option><option value="research">购买调研</option><option value="support">使用支持</option></select></label></ActionForm>
          <ResourceBlock resource={data.suggestions}>{(items) => items.map((item) => <div
            className={styles.row} data-testid={item.query_cluster_key ? undefined : "legacy-query-suggestion"}
            key={item.id}>
            <span className={styles.rowHeader}><strong>{item.query_text}</strong><Status value={item.status} /></span>
            <span className={styles.meta}>{item.query_cluster_key
              ? `问题簇：${item.query_cluster_key}` : "迁移历史 · 缺少问题簇 · 只读"}</span>
            {item.status === "suggested" && item.query_cluster_key ? <ActionForm
              action={approveSuggestion} submitLabel="批准建议">
              <HiddenProject projectId={projectId} />
              <input type="hidden" name="campaign_id" value={selection.campaignId || ""} />
              <input type="hidden" name="protocol_id" value={item.protocol_id} />
              <input type="hidden" name="suggestion_id" value={item.id} />
            </ActionForm> : item.status === "suggested" ? <div className={styles.metricWarning}>
              旧记录没有冻结问题簇，不能批准。请在上方提交包含问题簇的新建议。
            </div> : null}
          </div>)}</ResourceBlock></section>
        <section className={styles.unframed}><h3>指标与报告</h3><ActionForm action={computeMetrics} submitLabel="计算指标" disabled={!selectedProtocol || sourceStrata.length === 0 || queryClusters.length === 0}><HiddenProject projectId={projectId} /><input type="hidden" name="campaign_id" value={selection.campaignId || ""} /><input type="hidden" name="protocol_id" value={selectedProtocol?.id || ""} /><label>来源分层<select name="source_stratum_hash" required defaultValue=""><option value="" disabled>选择冻结来源分层</option>{sourceStrata.map((item) => <option key={item.hash} value={item.hash}>{item.label}</option>)}</select></label><label>问题簇<select name="query_cluster_key" required defaultValue=""><option value="" disabled>选择冻结问题簇</option>{queryClusters.map((item) => <option key={item} value={item}>{item}</option>)}</select></label><label>测量窗口<select name="measurement_window" defaultValue={selection.measurementWindow}><option value="baseline">基线</option><option value="t28">T+28</option><option value="t56">T+56</option><option value="t84">T+84</option><option value="ad_hoc">临时测量</option></select></label></ActionForm>
          <ResourceBlock resource={data.metrics}>{(items) => items.length ? <div className={styles.metricList}>{items.map((metric) => <MonitoringMetricSnapshot metric={metric} key={metric.id} />)}</div> : <Empty>尚无指标快照。</Empty>}</ResourceBlock>
          <ActionForm action={createReport} submitLabel="生成报告" disabled={data.metrics.data.length === 0}><HiddenProject projectId={projectId} /><input type="hidden" name="campaign_id" value={selection.campaignId || ""} /><label>指标快照<select name="metric_snapshot_id" required defaultValue=""><option value="" disabled>选择快照</option>{data.metrics.data.map((item) => <option key={item.id} value={item.id}>{item.measurement_window} · {(item.source_stratum_hash || "unknown").slice(0, 8)} · {item.computed_at}</option>)}</select></label><label>报告标题<input name="title" required /></label></ActionForm>
          <ResourceBlock resource={data.reports}>{(items) => items.map((report) => <div className={styles.row} key={report.id}><span className={styles.rowHeader}><strong>{report.title}</strong><Status value={report.status} /></span>{report.status === "draft" ? <ActionForm action={approveReport} submitLabel="批准报告"><HiddenProject projectId={projectId} /><input type="hidden" name="campaign_id" value={selection.campaignId || ""} /><input type="hidden" name="report_id" value={report.id} /></ActionForm> : null}</div>)}</ResourceBlock></section>
      </div>
    </CommandPanel>
  </section>;
}

function queryKindLabel(value: string) { return ({ recommendation: "商品推荐", comparison: "产品比较", research: "购买调研", support: "使用支持" } as Record<string, string>)[value] || value; }
function platformLabel(value: string) { return ({ chatgpt_search: "ChatGPT Search", google_ai_overviews: "Google AI Overviews", google_search: "Google Search", perplexity: "Perplexity", gemini: "Gemini" } as Record<string, string>)[value] || value; }
function deviceLabel(value: string) { return ({ desktop: "桌面端", mobile: "移动端", tablet: "平板" } as Record<string, string>)[value] || value; }
