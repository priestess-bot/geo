import { ActionForm } from "./ActionForm";
import { createDestination, reviewDestination, transitionOpportunity } from "./campaign-actions";
import { CommandPanel, Empty, geoHref, HiddenProject, ResourceBlock, Status, TechnicalInfo } from "./common";
import { channelLabel, commandLabel, opportunityRationale } from "./display";
import type { GeoWorkspaceData } from "./model";
import styles from "./GeoWorkspace.module.css";

const channels = ["owned_site", "productreview", "youtube", "reddit", "amazon", "ozbargain", "tiktok", "instagram", "quora"] as const;

export function DestinationWorkspace({ projectId, data }: { projectId: string; data: GeoWorkspaceData }) {
  const { selection } = data;
  const destination = data.destinations.data.find((item) => item.id === selection.destinationId);
  return <section className={styles.workspace}>
    <header className={styles.pageHeading}><div><h2>渠道计划</h2><p>查看每个平台的账号、政策准备度、阻断原因和当前 Campaign 任务。</p></div>
      <CommandPanel label="新增渠道任务"><CreateDestinationForm projectId={projectId} /></CommandPanel>
    </header>

    <section className={styles.panel}>
      <table className={styles.table}><thead><tr><th>渠道</th><th>目标位置</th><th>操作方式</th><th>政策状态</th><th>任务</th></tr></thead><tbody>
        {channels.map((channel) => {
          const records = data.destinations.data.filter((item) => item.publication_channel === channel);
          const item = records[0];
          return <tr key={channel}><td><strong>{channelLabel(channel)}</strong></td><td>{item ? <a href={geoHref(projectId, selection, { destination_id: item.id })}>{item.destination_key}</a> : "尚未配置"}</td><td>{item ? operationLabel(item.operation_mode || "manual") : "-"}</td><td><Status value={item?.policy_status || "missing"} /></td><td>{records.length ? `${records.length} 个` : "0"}</td></tr>;
        })}
      </tbody></table>
    </section>

    <div className={styles.columns}>
      <section className={styles.panel}>
        <div className={styles.sectionHeader}><div><p>当前选择</p><h2>{destination ? channelLabel(destination.publication_channel) : "选择渠道"}</h2></div>{destination ? <Status value={destination.policy_status} /> : null}</div>
        {destination ? <><div className={styles.keyValues}><div><span className={styles.meta}>目标位置</span><br /><strong>{destination.destination_key}</strong></div><div><span className={styles.meta}>域名</span><br /><strong>{destination.canonical_host}</strong></div><div><span className={styles.meta}>方式</span><br /><strong>{operationLabel(destination.operation_mode || "manual")}</strong></div></div>
          <p><a href={destination.canonical_url} target="_blank" rel="noreferrer">打开目标页面</a></p><TechnicalInfo><code>Destination {destination.id}</code><code>{destination.canonical_url}</code></TechnicalInfo></> : <Empty>从上方渠道表选择一个任务，查看政策和执行要求。</Empty>}
        <h3>政策记录</h3><ResourceBlock resource={data.policyReviews}>{(reviews) => reviews.length ? <div className={styles.list}>{reviews.map((review) => <div className={styles.row} key={review.id}><span className={styles.rowHeader}><strong>版本 {review.version_number}</strong><Status value={review.status} /></span><span className={styles.meta}>{new Date(review.reviewed_at).toLocaleDateString("zh-CN")} · 允许域名 {review.allowed_hosts.join(", ")}</span></div>)}</div> : <Empty>还没有政策复核记录，相关投放任务不能进入内容生产。</Empty>}</ResourceBlock>
      </section>
      <section className={styles.unframed}><CommandPanel label="复核或更新渠道政策"><PolicyReviewForm projectId={projectId} destination={destination} /></CommandPanel></section>
    </div>

    <section className={styles.panel}>
      <div className={styles.sectionHeader}><div><p>当前 Campaign</p><h2>渠道投放任务</h2></div><span className={styles.meta}>{data.opportunities.data.length} 个任务</span></div>
      <ResourceBlock resource={data.opportunities}>{(items) => items.length ? <table className={styles.table}><thead><tr><th>渠道</th><th>任务说明</th><th>状态</th><th>操作</th></tr></thead><tbody>{items.map((item) => {
        const target = data.destinations.data.find((candidate) => candidate.id === item.destination_id);
        return <tr key={item.id}><td><strong>{channelLabel(target?.publication_channel || "other")}</strong><div className={styles.meta}>{target?.destination_key}</div></td><td>{opportunityRationale(item.rationale)}</td><td><Status value={item.status} /></td><td><details className={styles.rowActions}><summary>操作</summary><div className={styles.toolbar}>{item.allowed_commands.map((command) => <ActionForm action={transitionOpportunity} submitLabel={commandLabel(command)} key={command} danger={command === "block" || command === "cancel"}><HiddenProject projectId={projectId} /><input type="hidden" name="opportunity_id" value={item.id} /><input type="hidden" name="command" value={command} /><input type="hidden" name="reason" value={`Admin workspace: ${command}`} /></ActionForm>)}</div><TechnicalInfo><code>{item.id}</code><code>{item.opportunity_ref}</code></TechnicalInfo></details></td></tr>;
      })}</tbody></table> : <Empty>创建 Campaign 时会为所选渠道生成投放任务。</Empty>}</ResourceBlock>
    </section>
  </section>;
}

function CreateDestinationForm({ projectId }: { projectId: string }) {
  return <ActionForm action={createDestination} submitLabel="创建渠道任务"><HiddenProject projectId={projectId} />
    <label>平台<select name="publication_channel" defaultValue="productreview">{channels.map((channel) => <option value={channel} key={channel}>{channelLabel(channel)}</option>)}</select></label>
    <label>任务名称<input name="destination_key" required placeholder="例如：ADVINSYS ProductReview 商家账号" /></label>
    <label>目标页面 URL<input name="canonical_url" type="url" required placeholder="https://..." /></label>
    <label>账号或店铺标识<input name="destination_account_id" placeholder="可选，用于区分同平台多个账号" /></label>
    <label>执行方式<select name="operation_mode" defaultValue="manual"><option value="manual">人工发布</option><option value="assisted">系统辅助、人工确认</option></select></label>
  </ActionForm>;
}

function PolicyReviewForm({ projectId, destination }: { projectId: string; destination: GeoWorkspaceData["destinations"]["data"][number] | undefined }) {
  return <ActionForm action={reviewDestination} submitLabel="保存政策复核" disabled={!destination}><HiddenProject projectId={projectId} /><input type="hidden" name="destination_id" value={destination?.id || ""} />
    <label>结论<select name="status" defaultValue="approved"><option value="approved">允许执行</option><option value="restricted">满足条件后允许</option><option value="prohibited">禁止执行</option></select></label>
    <label>允许发布的域名<textarea name="allowed_hosts" required defaultValue={destination?.canonical_host || ""} placeholder="每行一个域名" /></label>
    <label className={styles.check}><input type="checkbox" name="manual_submission" defaultChecked />必须由人工提交</label><label className={styles.check}><input type="checkbox" name="automated_posting" />允许自动发布</label><label className={styles.check}><input type="checkbox" name="original_context_required" defaultChecked />发布前必须确认原始问题、评价或优惠上下文</label>
    <label>发布身份<select name="brand_identity" defaultValue="disclosed"><option value="disclosed">明确披露品牌身份</option><option value="merchant">商家或卖家身份</option><option value="creator_partnership">已披露合作创作者</option></select></label>
    <label className={styles.check}><input type="checkbox" name="authorised_account_required" defaultChecked />必须使用已授权账号</label>
    <label>商业关系披露<select name="commercial_relationship" defaultValue="disclose_when_required"><option value="disclose_when_required">平台要求时披露</option><option value="always_disclose">始终披露</option><option value="not_applicable">不适用</option></select></label>
    <label className={styles.check}><input type="checkbox" name="source_attribution_required" defaultChecked />内容中的事实需要来源归属</label>
  </ActionForm>;
}

function operationLabel(value: string) { return ({ manual: "人工发布", assisted: "系统辅助", api: "API 发布" } as Record<string, string>)[value] || value; }
