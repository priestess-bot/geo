import Link from "next/link";
import { ActionForm } from "./ActionForm";
import { createDestination, reviewDestination, transitionOpportunity } from "./campaign-actions";
import { Empty, HiddenProject, ResourceBlock, SectionHeader, ShortId, Status, geoHref } from "./common";
import type { GeoWorkspaceData } from "./model";
import styles from "./GeoWorkspace.module.css";

const channels = ["owned_site", "productreview", "youtube", "reddit", "amazon", "ozbargain", "tiktok", "instagram", "quora"] as const;

export function DestinationWorkspace({ projectId, data }: { projectId: string; data: GeoWorkspaceData }) {
  const { selection } = data;
  const destination = data.destinations.data.find((item) => item.id === selection.destinationId);
  return <section className={styles.workspace}>
    <SectionHeader eyebrow="Governed distribution" title="九渠道任务、政策复核与机会资格" />
    <div className={styles.panel}>
      <h3>渠道覆盖</h3>
      <div className={styles.channelGrid}>{channels.map((channel) => {
        const records = data.destinations.data.filter((item) => item.publication_channel === channel);
        return <a href="#destination-form" className={styles.channel} key={channel}><strong>{channel}</strong>
          <span className={styles.meta}>{records.length ? `${records.length} 个任务` : "待建立任务"}</span>
          <Status value={records.some((item) => item.policy_status === "approved") ? "policy approved" : records[0]?.policy_status || "missing"} />
        </a>;
      })}</div>
    </div>
    <div className={styles.split}>
      <aside className={`${styles.workspace} ${styles.sticky}`}>
        <div className={styles.panel}><h3>渠道目的地</h3><ResourceBlock resource={data.destinations}>{(items) => items.length ? <div className={styles.list}>{items.map((item) => <Link
          className={item.id === selection.destinationId ? styles.selectedRow : styles.row} key={item.id}
          href={geoHref(projectId, selection, { destination_id: item.id })}>
          <span className={styles.rowHeader}><strong>{item.publication_channel}</strong><Status value={item.policy_status} /></span>
          <span className={styles.meta}><span>{item.destination_key}</span><span>{item.operation_mode}</span></span>
        </Link>)}</div> : <Empty>尚无渠道目的地。</Empty>}</ResourceBlock></div>
        <div className={styles.panel} id="destination-form">
          <ActionForm action={createDestination} title="建立渠道任务" submitLabel="创建目的地">
            <HiddenProject projectId={projectId} />
            <label>渠道<select name="publication_channel" defaultValue="productreview">{channels.map((channel) => <option value={channel} key={channel}>{channel}</option>)}</select></label>
            <label>目的地 Key<input name="destination_key" required placeholder="productreview-au-brand-account" /></label>
            <label>规范 URL<input name="canonical_url" type="url" required placeholder="https://www.productreview.com.au/..." /></label>
            <label>账号 ID<input name="destination_account_id" placeholder="可选；区分同平台多账号" /></label>
            <label>操作方式<select name="operation_mode" defaultValue="manual"><option value="manual">人工投放</option><option value="assisted">辅助投放</option></select></label>
          </ActionForm>
        </div>
      </aside>
      <div className={styles.workspace}>
        <div className={styles.columns}>
          <div className={styles.panel}>
            <h3>当前政策基线</h3>
            {destination ? <><div className={styles.keyValues}><div><span className={styles.meta}>渠道</span><br /><strong>{destination.publication_channel}</strong></div><div><span className={styles.meta}>Host</span><br /><strong>{destination.canonical_host}</strong></div><div><span className={styles.meta}>模式</span><br /><strong>{destination.operation_mode}</strong></div></div>
              <a href={destination.canonical_url} target="_blank" rel="noreferrer">{destination.canonical_url}</a></> : <Empty>选择一个渠道目的地。</Empty>}
            <ResourceBlock resource={data.policyReviews}>{(reviews) => reviews.length ? <div className={styles.list}>{reviews.map((review) => <div className={styles.row} key={review.id}><span className={styles.rowHeader}><strong>政策 v{review.version_number}</strong><Status value={review.status} /></span><span className={styles.meta}><span>{review.allowed_hosts.join(", ")}</span><span>{new Date(review.reviewed_at).toLocaleDateString("zh-CN")}</span></span></div>)}</div> : <Empty>尚未完成政策复核，机会不可资格化。</Empty>}</ResourceBlock>
          </div>
          <div className={styles.panel}>
            <ActionForm action={reviewDestination} title="新增政策复核版本" submitLabel="保存政策复核" disabled={!destination}>
              <HiddenProject projectId={projectId} /><input type="hidden" name="destination_id" value={destination?.id || ""} />
              <label>结论<select name="status" defaultValue="approved"><option value="approved">允许</option><option value="restricted">受限</option><option value="prohibited">禁止</option></select></label>
              <label>允许 Host<textarea name="allowed_hosts" required defaultValue={destination?.canonical_host || ""} /></label>
              <label>平台规则 JSON<textarea name="rules" defaultValue={'{"manual_submission":true,"automated_posting":false}'} required /></label>
              <label>身份要求 JSON<textarea name="identity_requirements" defaultValue={'{"brand_identity":"disclosed"}'} required /></label>
              <label>披露要求 JSON<textarea name="disclosure_requirements" defaultValue={'{"commercial_relationship":"disclose_when_required"}'} required /></label>
            </ActionForm>
          </div>
        </div>
        <div className={styles.panel}>
          <SectionHeader eyebrow="Publication intent" title="Campaign 投放机会">
            <span className={styles.meta}>选择 Campaign 查看其渠道投放任务</span>
          </SectionHeader>
          <div className={styles.toolbar}>{data.campaigns.data.map((campaign) => <Link className={campaign.id === selection.campaignId ? "button" : "button secondary"} key={campaign.id}
            href={geoHref(projectId, selection, { campaign_id: campaign.id, opportunity_id: undefined })}>{campaign.name}</Link>)}</div>
          <ResourceBlock resource={data.opportunities}>{(items) => items.length ? <div className={styles.list}>{items.map((item) => {
            const channel = data.destinations.data.find((candidate) => candidate.id === item.destination_id)?.publication_channel || "unknown";
            return <div className={styles.row} key={item.id}>
              <span className={styles.rowHeader}><strong>{channel} · {item.opportunity_ref}</strong><Status value={item.status} /></span>
              <span className={styles.meta}><span>{item.rationale}</span><ShortId value={item.id} /></span>
              <div className={styles.toolbar}>{item.allowed_commands.map((command) => <ActionForm action={transitionOpportunity} submitLabel={command} key={command} danger={command === "block" || command === "cancel"}>
                <HiddenProject projectId={projectId} /><input type="hidden" name="opportunity_id" value={item.id} /><input type="hidden" name="command" value={command} /><input type="hidden" name="reason" value={`Admin workspace: ${command}`} />
              </ActionForm>)}</div>
            </div>;
          })}</div> : <Empty>创建 Campaign 时会为所选渠道生成机会任务。</Empty>}</ResourceBlock>
        </div>
      </div>
    </div>
  </section>;
}
