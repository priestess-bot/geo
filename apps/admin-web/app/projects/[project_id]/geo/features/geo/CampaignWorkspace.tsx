import Link from "next/link";
import { ActionForm } from "./ActionForm";
import { approveReport, approveSuggestion, changeProtocol, computeMetrics, createCampaign, createMonitoringQuery, createProtocol, createReport, createSuggestion } from "./campaign-actions";
import { Empty, HiddenProject, ResourceBlock, SectionHeader, ShortId, Status, geoHref } from "./common";
import type { GeoWorkspaceData } from "./model";
import styles from "./GeoWorkspace.module.css";

export function CampaignWorkspace({ projectId, data }: { projectId: string; data: GeoWorkspaceData }) {
  const { selection } = data;
  const selectedCampaign = data.campaigns.data.find((item) => item.id === selection.campaignId);
  const selectedProtocol = data.protocols.data.find((item) => item.id === selection.protocolId);
  return <section className={styles.workspace}>
    <SectionHeader eyebrow="Campaign operations" title="Campaign、消费者查询与监测闭环" />
    <div className={styles.split}>
      <aside className={`${styles.workspace} ${styles.sticky}`}>
        <div className={styles.panel}>
          <h3>Campaign</h3>
          <ResourceBlock resource={data.campaigns}>{(campaigns) => campaigns.length ? <div className={styles.list}>{campaigns.map((campaign) =>
            <Link key={campaign.id} className={campaign.id === selection.campaignId ? styles.selectedRow : styles.row}
              href={geoHref(projectId, selection, { campaign_id: campaign.id, opportunity_id: undefined, brief_version_id: undefined })}>
              <span className={styles.rowHeader}><strong>{campaign.name}</strong><Status value={campaign.status} /></span>
              <span className={styles.meta}><span>{campaign.objective}</span><ShortId value={campaign.id} /></span>
            </Link>)}</div> : <Empty>尚未创建 Campaign。</Empty>}</ResourceBlock>
        </div>
        <div className={styles.panel}>
          <ActionForm action={createCampaign} title="创建 Campaign" submitLabel="创建并建立渠道任务" disabled={data.destinations.data.length === 0}>
            <HiddenProject projectId={projectId} />
            <label>名称<input name="name" required placeholder="AU Robot Vacuum Recommendations" /></label>
            <label>Market Profile ID<input name="market_profile_id" required placeholder="UUID" /></label>
            <label>主商品实体 ID<input name="primary_product_entity_id" required placeholder="UUID" /></label>
            <label>目标渠道<select name="destination_ids" required multiple size={Math.min(6, Math.max(2, data.destinations.data.length))}>
              {data.destinations.data.map((item) => <option key={item.id} value={item.id}>{item.publication_channel} · {item.destination_key}</option>)}
            </select></label>
            <label>目标<input name="objective" defaultValue="recommendation_influence" required /></label>
            <label>机会依据<textarea name="opportunity_rationale" required placeholder="为什么这些渠道和查询值得投放" /></label>
          </ActionForm>
          {data.destinations.data.length === 0 ? <p className={styles.meta}>先在“渠道与机会”中建立至少一个目的地。</p> : null}
        </div>
      </aside>
      <div className={styles.workspace}>
        <div className={styles.columns}>
          <div className={styles.panel}>
            <h3>消费者查询</h3>
            <ResourceBlock resource={data.queries}>{(queries) => queries.length ? <div className={styles.list}>{queries.map((query) => <div className={styles.row} key={query.id}>
              <span className={styles.rowHeader}><strong>{query.query_text}</strong><Status value={query.status} /></span>
              <span className={styles.meta}><span>{query.query_kind}</span><span>{query.locale}</span><ShortId value={query.id} /></span>
            </div>)}</div> : <Empty>当前 Campaign 尚无消费者查询。</Empty>}</ResourceBlock>
          </div>
          <div className={styles.panel}>
            <ActionForm action={createMonitoringQuery} title="添加真实问法" submitLabel="添加查询" disabled={!selectedCampaign}>
              <HiddenProject projectId={projectId} /><input type="hidden" name="campaign_id" value={selectedCampaign?.id || ""} />
              <label>Market Profile ID<input name="market_profile_id" required defaultValue={selectedCampaign?.market_profile_id || ""} /></label>
              <label>消费者问题<textarea name="query_text" required placeholder="Which robot vacuum is best for pet hair?" /></label>
              <div className={styles.inline}><label>意图<select name="query_kind" defaultValue="recommendation"><option value="recommendation">推荐</option><option value="comparison">比较</option><option value="research">调研</option><option value="support">支持</option></select></label>
                <label>Locale<input name="locale" defaultValue="en-AU" required /></label></div>
            </ActionForm>
          </div>
        </div>
        <div className={styles.panel}>
          <SectionHeader eyebrow="Measurement contract" title="监测协议">
            <span className={styles.meta}>批准后可导入观察；冻结后保持口径不可漂移</span>
          </SectionHeader>
          <div className={styles.columns}>
            <ResourceBlock resource={data.protocols}>{(protocols) => protocols.length ? <div className={styles.list}>{protocols.map((protocol) => <Link key={protocol.id}
              className={protocol.id === selection.protocolId ? styles.selectedRow : styles.row}
              href={geoHref(projectId, selection, { protocol_id: protocol.id })}>
              <span className={styles.rowHeader}><strong>{protocol.name}</strong><Status value={protocol.status} /></span>
              <span className={styles.meta}><span>{protocol.platform}</span><span>{protocol.locale}/{protocol.device}</span><span>{protocol.sample_size} samples</span></span>
            </Link>)}</div> : <Empty>尚无监测协议。</Empty>}</ResourceBlock>
            <ActionForm action={createProtocol} title="新建监测协议" submitLabel="保存协议" disabled={!selectedCampaign}>
              <HiddenProject projectId={projectId} /><input type="hidden" name="campaign_id" value={selectedCampaign?.id || ""} />
              <label>名称<input name="name" required placeholder="ChatGPT AU baseline" /></label>
              <label>Market Profile ID<input name="market_profile_id" required defaultValue={selectedCampaign?.market_profile_id || ""} /></label>
              <div className={styles.inline}><label>平台<select name="platform" defaultValue="chatgpt_search"><option value="chatgpt_search">ChatGPT Search</option><option value="google_ai_overviews">Google AI Overviews</option><option value="google_search">Google Search</option><option value="perplexity">Perplexity</option><option value="gemini">Gemini</option><option value="other">其他</option></select></label>
                <label>设备<select name="device" defaultValue="desktop"><option value="desktop">Desktop</option><option value="mobile">Mobile</option><option value="tablet">Tablet</option></select></label></div>
              <div className={styles.inline}><label>Locale<input name="locale" defaultValue="en-AU" required /></label><label>样本数<input name="sample_size" type="number" min="1" max="1000" defaultValue="3" required /></label></div>
              <label>窗口天数<input name="window_days" type="number" min="1" max="365" defaultValue="28" required /></label>
            </ActionForm>
          </div>
          {selectedProtocol ? <div className={styles.toolbar}>
            {selectedProtocol.status === "draft" ? <ActionForm action={changeProtocol} submitLabel="批准协议"><HiddenProject projectId={projectId} /><input type="hidden" name="protocol_id" value={selectedProtocol.id} /><input type="hidden" name="command" value="approve" /></ActionForm> : null}
            {selectedProtocol.status === "approved" ? <ActionForm action={changeProtocol} submitLabel="冻结协议"><HiddenProject projectId={projectId} /><input type="hidden" name="protocol_id" value={selectedProtocol.id} /><input type="hidden" name="command" value="freeze" /></ActionForm> : null}
          </div> : null}
        </div>
        <div className={styles.columns}>
          <div className={styles.panel}>
            <h3>查询建议</h3>
            <ActionForm action={createSuggestion} submitLabel="提交建议" disabled={!selectedProtocol}>
              <HiddenProject projectId={projectId} /><input type="hidden" name="protocol_id" value={selectedProtocol?.id || ""} />
              <label>问法<textarea name="query_text" required /></label><label>依据<textarea name="rationale" required /></label>
              <label>类型<select name="query_kind" defaultValue="recommendation"><option value="recommendation">推荐</option><option value="comparison">比较</option><option value="research">调研</option><option value="support">支持</option></select></label>
            </ActionForm>
            <ResourceBlock resource={data.suggestions}>{(items) => items.map((item) => <div className={styles.row} key={item.id}><span className={styles.rowHeader}><strong>{item.query_text}</strong><Status value={item.status} /></span>
              {item.status === "suggested" ? <ActionForm action={approveSuggestion} submitLabel="批准"><HiddenProject projectId={projectId} /><input type="hidden" name="protocol_id" value={item.protocol_id} /><input type="hidden" name="suggestion_id" value={item.id} /></ActionForm> : null}</div>)}</ResourceBlock>
          </div>
          <div className={styles.panel}>
            <h3>指标与报告</h3>
            <ActionForm action={computeMetrics} submitLabel="计算指标" disabled={!selectedProtocol}>
              <HiddenProject projectId={projectId} /><input type="hidden" name="protocol_id" value={selectedProtocol?.id || ""} />
              <label>测量窗口<select name="measurement_window" defaultValue={selection.measurementWindow}><option value="baseline">Baseline</option><option value="t28">T+28</option><option value="t56">T+56</option><option value="t84">T+84</option><option value="ad_hoc">Ad hoc</option></select></label>
            </ActionForm>
            <ResourceBlock resource={data.metrics}>{(items) => items.length ? <div className={styles.list}>{items.map((metric) => <div className={styles.row} key={metric.id}><span className={styles.rowHeader}><strong>{metric.measurement_window} · recommendation {(metric.recommendation_share * 100).toFixed(1)}%</strong><Status value={metric.status} /></span><span className={styles.meta}>eligible {metric.eligible_sample_count}/{metric.expected_sample_count} · citation {(metric.placement_citation_share * 100).toFixed(1)}%</span></div>)}</div> : <Empty>尚无指标快照。</Empty>}</ResourceBlock>
            <ActionForm action={createReport} submitLabel="生成报告" disabled={data.metrics.data.length === 0}>
              <HiddenProject projectId={projectId} /><label>指标快照<select name="metric_snapshot_id" required defaultValue=""><option value="" disabled>选择快照</option>{data.metrics.data.map((item) => <option key={item.id} value={item.id}>{item.measurement_window} · {item.computed_at}</option>)}</select></label><label>报告标题<input name="title" required /></label>
            </ActionForm>
            <ResourceBlock resource={data.reports}>{(items) => items.map((report) => <div className={styles.row} key={report.id}><span className={styles.rowHeader}><strong>{report.title}</strong><Status value={report.status} /></span>{report.status === "draft" ? <ActionForm action={approveReport} submitLabel="批准报告"><HiddenProject projectId={projectId} /><input type="hidden" name="report_id" value={report.id} /></ActionForm> : null}</div>)}</ResourceBlock>
          </div>
        </div>
      </div>
    </div>
  </section>;
}
