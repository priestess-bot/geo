import { ActionForm } from "./ActionForm";
import { bindOpportunityPromptRelease, buildEvidence, createBrief, createPromptBundle, createPromptRelease, createPromptSkill, installDefaultPromptCatalog, transitionPromptRelease } from "./placement-actions";
import { CommandPanel, Empty, geoHref, HiddenProject, ResourceBlock, Status, TechnicalInfo } from "./common";
import { channelLabel, entityName } from "./display";
import type { GeoWorkspaceData } from "./model";
import type { CatalogLoadResult } from "../../../catalogTypes";
import styles from "./GeoWorkspace.module.css";
import { DEFAULT_OUTPUT_SCHEMA } from "./prompt-defaults";

const MODEL_POLICY_HASH = "18d6221a72c4f929f2b3e04f089f7c72ec9d32ad811e1e1443cd34dcc8df61b7";

export function BriefPromptPanel({ projectId, data, catalog, mode }: {
  projectId: string; data: GeoWorkspaceData; catalog: CatalogLoadResult; mode: "brief" | "evidence";
}) {
  const { selection } = data;
  const opportunity = data.opportunities.data.find((item) => item.id === selection.opportunityId);
  const brief = data.briefs.data.find((item) => item.id === selection.briefVersionId);
  const readyAttempt = data.attempts.data.find((item) => item.id === selection.attemptId && item.status === "ready");
  return mode === "brief"
    ? <BriefStep projectId={projectId} data={data} catalog={catalog} opportunityId={opportunity?.id} brief={brief} />
    : <EvidenceStep projectId={projectId} data={data} brief={brief} readyAttempt={readyAttempt} />;
}

function BriefStep({ projectId, data, catalog, opportunityId, brief }: {
  projectId: string; data: GeoWorkspaceData; catalog: CatalogLoadResult; opportunityId?: string; brief: GeoWorkspaceData["briefs"]["data"][number] | undefined;
}) {
  const brands = catalog.entities.data.filter((item) => item.entity_type === "brand");
  const subjects = catalog.entities.data.filter((item) => item.entity_type !== "competitor");
  const competitors = catalog.entities.data.filter((item) => item.entity_type === "competitor");
  return <div className={styles.columns}>
    <section className={styles.panel}>
      <div className={styles.sectionHeader}><div><p>当前内容要求</p><h2>Brief 版本</h2></div><span className={styles.meta}>{data.briefs.data.length} 个版本</span></div>
      <ResourceBlock resource={data.briefs}>{(items) => items.length ? <div className={styles.list}>{items.map((item) => <div key={item.id} className={item.id === data.selection.briefVersionId ? styles.selectedRow : styles.row}><a href={geoHref(projectId, data.selection, { brief_version_id: item.id, attempt_id: undefined, bundle_id: undefined })}><span className={styles.rowHeader}><strong>版本 {item.version_number}</strong>{item.id === brief?.id ? <Status value="active" /> : null}</span></a><TechnicalInfo><code>{item.id}</code><code>{item.content_hash}</code></TechnicalInfo></div>)}</div> : <Empty>先创建一份内容要求，系统才会为当前渠道准备证据。</Empty>}</ResourceBlock>
      {brief ? <><h3>已冻结目标</h3><div className={styles.content}>{briefSummary(brief.goals)}</div><a className="button" href={geoHref(projectId, data.selection, { placement_stage: "evidence", brief_version_id: brief.id })}>继续选择证据</a></> : null}
    </section>
    <section className={styles.panel}>
      <div className={styles.sectionHeader}><div><p>{brief ? "创建修订版本" : "第一步"}</p><h2>填写内容要求</h2></div></div>
      <ActionForm action={createBrief} submitLabel={brief ? "保存新版本" : "保存内容要求"} disabled={!opportunityId}>
        <HiddenProject projectId={projectId} /><input type="hidden" name="campaign_id" value={data.selection.campaignId || ""} /><input type="hidden" name="opportunity_id" value={opportunityId || ""} /><input type="hidden" name="base_version_id" value={brief?.id || ""} />
        <label>品牌<select name="primary_brand_entity_id" required defaultValue={brands[0]?.id || ""}>{brands.map((item) => <option key={item.id} value={item.id}>{item.canonical_name}</option>)}</select></label>
        <label>目标受众<input name="audience" required defaultValue="Australian consumers" placeholder="例如：澳大利亚中型草坪家庭" /></label>
        <label>内容目标<select name="intent" defaultValue="product recommendation"><option value="product recommendation">商品推荐</option><option value="product comparison">产品比较</option><option value="buying guide">购买指南</option><option value="expert answer">专业问答</option></select></label>
        <label>交付内容<select name="deliverable" defaultValue="channel-ready copy"><option value="channel-ready copy">适合当前渠道发布的文案</option><option value="article draft">文章草稿</option><option value="video script">视频脚本</option><option value="merchant response">商家回复</option></select></label>
        <label>需要表达的卖点<textarea name="value_propositions" placeholder="每行一个卖点；生成时仍必须有证据支持" /></label>
        <label>允许使用的事实主体<select name="allowed_subject_entity_ids" multiple size={Math.min(6, Math.max(3, subjects.length))}>{subjects.map((item) => <option key={item.id} value={item.id}>{item.canonical_name}</option>)}</select></label>
        {competitors.length ? <label>比较对象<select name="compared_entity_ids" multiple size={Math.min(5, competitors.length)}>{competitors.map((item) => <option key={item.id} value={item.id}>{item.canonical_name}</option>)}</select></label> : null}
        <fieldset><legend>生成约束</legend><label className={styles.check}><input type="checkbox" name="public_citations_required" defaultChecked />公开事实必须带可公开引用来源</label><label className={styles.check}><input type="checkbox" name="commercial_disclosure_required" defaultChecked />需要时披露品牌或商业关系</label><label className={styles.check}><input type="checkbox" name="unsupported_superlatives" />允许无证据的最高级表述</label><label>字数上限<input name="maximum_words" type="number" min="50" max="5000" defaultValue="500" /></label></fieldset>
        <details><summary>消费者使用描述（可选）</summary><div className={styles.formInset}><label>真实使用描述<textarea name="consumer_experience_description" placeholder="粘贴一段已获授权的真实消费者使用描述" /></label><label>来源<input name="consumer_experience_source" placeholder="访谈、授权评论或客服记录" /></label><div className={styles.inline}><label>使用权<input name="consumer_experience_usage_rights" defaultValue="public_rewrite_authorized" /></label><label>披露方式<input name="consumer_experience_disclosure" defaultValue="customer statement, edited for clarity" /></label></div></div></details>
      </ActionForm>
    </section>
  </div>;
}

function EvidenceStep({ projectId, data, brief, readyAttempt }: {
  projectId: string; data: GeoWorkspaceData; brief: GeoWorkspaceData["briefs"]["data"][number] | undefined;
  readyAttempt: GeoWorkspaceData["attempts"]["data"][number] | undefined;
}) {
  const binding = data.promptBinding.data;
  const readiness = data.placementReadiness.data?.channels.find(
    (item) => item.opportunity_id === data.selection.opportunityId
  );
  return <div className={styles.workspace}>
    {!brief ? <div className={styles.notice}><span>需要先完成内容要求。</span><a href={geoHref(projectId, data.selection, { placement_stage: "brief" })}>返回第一步</a></div> : null}
    <div className={styles.columns}>
      <section className={styles.panel}><div className={styles.sectionHeader}><div><p>不可变证据快照</p><h2>证据准备</h2></div>{readyAttempt ? <Status value="ready" /> : null}</div>
        <ResourceBlock resource={data.attempts}>{(items) => items.length ? <div className={styles.list}>{items.map((item) => <div key={item.id} className={item.id === data.selection.attemptId ? styles.selectedRow : styles.row}><a href={geoHref(projectId, data.selection, { attempt_id: item.id })}><span className={styles.rowHeader}><strong>第 {item.attempt_number} 次构建</strong><Status value={item.status} /></span><span className={styles.meta}>{item.failure_reason || "已冻结所用来源与版本"}</span></a><TechnicalInfo><code>{item.id}</code><code>{item.pack_hash || "pending"}</code></TechnicalInfo></div>)}</div> : <Empty>尚未为当前 Brief 构建证据。</Empty>}</ResourceBlock>
        <ActionForm action={buildEvidence} submitLabel={data.attempts.data.length ? "重新构建证据" : "构建证据"} disabled={!brief}><HiddenProject projectId={projectId} /><input type="hidden" name="campaign_id" value={data.selection.campaignId || ""} /><input type="hidden" name="brief_version_id" value={brief?.id || ""} /></ActionForm>
        {data.job.data ? <div className={styles.notice}><span>证据任务：{data.job.data.status}</span><TechnicalInfo><code>{data.job.data.id}</code><span>{data.job.data.result_ref || data.job.data.error_code}</span></TechnicalInfo></div> : null}
      </section>
      <section className={styles.panel}><div className={styles.sectionHeader}><div><p>可追踪事实</p><h2>本次使用的证据</h2></div><span className={styles.meta}>{data.evidenceItems.data.length} 条</span></div>
        <ResourceBlock resource={data.evidenceItems}>{(items) => items.length ? <table className={styles.table}><thead><tr><th>事实或来源</th><th>使用权</th><th>公开引用</th></tr></thead><tbody>{items.map((item) => <tr key={item.id}><td><strong>{item.citation_label || item.public_source_title || item.item_type}</strong><div className={styles.meta}>{item.subject_role}</div></td><td>{item.usage_rights}</td><td>{item.public_disclosure_allowed ? "允许" : "仅内部"}{item.public_source_url ? <div><a href={item.public_source_url} target="_blank" rel="noreferrer">查看来源</a></div> : null}<TechnicalInfo><code>{item.id}</code><code>{item.snapshot_hash}</code>{item.knowledge_lineage ? <><code>Fact {item.knowledge_lineage.knowledge_fact_id}</code><code>{item.knowledge_lineage.lineage_contract_version}</code></> : null}</TechnicalInfo></td></tr>)}</tbody></table> : <Empty>证据构建成功后，这里会显示事实、使用权和公开引用资格。</Empty>}</ResourceBlock>
      </section>
    </div>
    <section className={styles.panel}><div className={styles.sectionHeader}><div><p>生成规则</p><h2>冻结本次生成输入</h2></div>{binding ? <Status value={binding.status} /> : null}</div>
      <PromptBindingIdentity binding={binding} />
      {readiness && !readiness.ready ? <div className={styles.notice}><span>{readiness.reasons.map(readinessReasonLabel).join("；")}</span></div> : null}
      <ActionForm action={createPromptBundle} submitLabel="确认并冻结生成输入" disabled={!brief || !readyAttempt || binding?.status !== "bound" || !binding.release_hash}><HiddenProject projectId={projectId} /><input type="hidden" name="campaign_id" value={data.selection.campaignId || ""} /><input type="hidden" name="opportunity_id" value={data.selection.opportunityId || ""} /><input type="hidden" name="brief_version_id" value={brief?.id || ""} /><input type="hidden" name="prompt_release_binding_id" value={binding?.id || ""} /><input type="hidden" name="confirmed_release_hash" value={binding?.release_hash || ""} /><input type="hidden" name="model_policy_hash" value={MODEL_POLICY_HASH} /><input type="hidden" name="variables" value="{}" />
        <label>证据版本<select name="evidence_pack_attempt_id" required defaultValue={readyAttempt?.id || ""}>{data.attempts.data.filter((item) => item.status === "ready").map((item) => <option key={item.id} value={item.id}>第 {item.attempt_number} 次构建 · 可使用</option>)}</select></label>
        <label className={styles.check}><input type="checkbox" name="confirm_prompt_release" required />确认使用以上 Prompt Release ID、版本与 hash</label>
      </ActionForm>
      <ResourceBlock resource={data.bundles}>{(items) => items.length ? <div className={styles.list}>{items.map((item, index) => <div key={item.id} className={item.id === data.selection.bundleId ? styles.selectedRow : styles.row}><a href={geoHref(projectId, data.selection, { bundle_id: item.id })}><span className={styles.rowHeader}><strong>生成输入 {items.length - index}</strong><Status value={item.artifact_status} /></span></a><TechnicalInfo><code>{item.id}</code><code>{item.bundle_hash}</code><span>{item.storage_uri || item.storage_key}</span></TechnicalInfo></div>)}</div> : <Empty>证据可用后，确认生成输入即可进入下一步。</Empty>}</ResourceBlock>
      {data.selection.bundleId ? <a className="button" href={geoHref(projectId, data.selection, { placement_stage: "generation" })}>继续生成文案</a> : null}
    </section>
    <PromptAdministration projectId={projectId} data={data} />
  </div>;
}

function PromptAdministration({ projectId, data }: { projectId: string; data: GeoWorkspaceData }) {
  const approvedReleases = data.releases.data.filter((item) => item.status === "approved");
  const currentBinding = data.promptBinding.data;
  return <CommandPanel label="高级：Prompt 规则与版本管理">
    <div className={styles.threeColumns}>
      <section className={styles.unframed}><h3>Prompt Skills</h3><ActionForm action={installDefaultPromptCatalog} submitLabel="同步九平台默认 Prompt"><HiddenProject projectId={projectId} /></ActionForm><ResourceBlock resource={data.skills}>{(items) => <div className={styles.list}>{items.map((item) => <a key={item.id} className={item.id === data.selection.skillId ? styles.selectedRow : styles.row} href={geoHref(projectId, data.selection, { skill_id: item.id })}><strong>{channelLabel(item.skill_key.split(".").at(-2) || item.skill_key)}</strong><Status value={item.status} /></a>)}</div>}</ResourceBlock><ActionForm action={createPromptSkill} submitLabel="创建 Skill"><HiddenProject projectId={projectId} /><label>Skill Key<input name="skill_key" required placeholder="placement.productreview.review" /></label></ActionForm></section>
      <section className={styles.unframed}><h3>不可变版本</h3><ResourceBlock resource={data.releases}>{(items) => items.length ? <div className={styles.list}>{items.map((item) => <PromptReleaseRow item={item} key={item.id} projectId={projectId} />)}</div> : <Empty>选择一个 Prompt Skill 查看其 Release。</Empty>}</ResourceBlock><ActionForm action={createPromptRelease} submitLabel="创建新版本" disabled={!data.selection.skillId}><HiddenProject projectId={projectId} /><input type="hidden" name="skill_id" value={data.selection.skillId || ""} /><label>规则源<textarea name="source" required /></label><label>System Prompt<textarea name="system_template" required /></label><label>User Prompt<textarea name="user_template" required /></label><label>输出结构 JSON<textarea name="output_schema" required defaultValue={DEFAULT_OUTPUT_SCHEMA} /></label><label>客户端变量<textarea name="client_variable_names" placeholder="每行一个" /></label></ActionForm></section>
      <section className={styles.unframed}><h3>当前 Opportunity 绑定</h3><PromptBindingIdentity binding={currentBinding} /><ActionForm action={bindOpportunityPromptRelease} submitLabel="确认并追加绑定" disabled={!data.selection.campaignId || !data.selection.opportunityId || !currentBinding || approvedReleases.length === 0}><HiddenProject projectId={projectId} /><input type="hidden" name="campaign_id" value={data.selection.campaignId || ""} /><input type="hidden" name="opportunity_id" value={data.selection.opportunityId || ""} /><input type="hidden" name="expected_binding_version" value={currentBinding?.binding_version || ""} /><label>已批准 Release<select name="template_release_id" required defaultValue=""><option value="" disabled>选择明确版本</option>{approvedReleases.map((item) => <option key={item.id} value={item.id}>{item.skill_key} · Skill v{item.skill_version} · Release {item.release_number}</option>)}</select></label><label>变更原因<textarea name="reason" required /></label></ActionForm><ResourceBlock resource={data.promptBindingHistory}>{(items) => items.length ? <div className={styles.list}>{items.map((item) => <div className={styles.row} key={item.id}><span className={styles.rowHeader}><strong>绑定 v{item.binding_version}</strong><Status value={item.status} /></span><span className={styles.meta}>{new Date(item.changed_at).toLocaleString("zh-CN")} · {item.changed_by || "legacy actor unknown"}</span><TechnicalInfo><code>{item.template_release_id || "unbound"}</code><code>{item.release_hash || "-"}</code></TechnicalInfo></div>)}</div> : <Empty>当前渠道任务还没有 Prompt 绑定历史。</Empty>}</ResourceBlock></section>
    </div>
  </CommandPanel>;
}

function PromptReleaseRow({ item, projectId }: {
  item: GeoWorkspaceData["releases"]["data"][number];
  projectId: string;
}) {
  const command = item.status === "draft" ? "approve" : item.status === "approved" ? "revoke" : null;
  return <div className={styles.row}>
    <span className={styles.rowHeader}><strong>Skill v{item.skill_version} · Release {item.release_number}</strong><Status value={item.status} /></span>
    <details><summary>查看 Prompt</summary><pre className={styles.code}>{item.system_template}</pre><pre className={styles.code}>{item.user_template}</pre></details>
    <TechnicalInfo><code>{item.id}</code><code>{item.release_hash}</code>{item.approved_by ? <span>{item.approved_by} · {item.approved_at ? new Date(item.approved_at).toLocaleString("zh-CN") : ""}</span> : null}</TechnicalInfo>
    {command ? <ActionForm action={transitionPromptRelease} submitLabel={command === "approve" ? "批准 Release" : "撤销 Release"} danger={command === "revoke"}>
      <HiddenProject projectId={projectId} />
      <input type="hidden" name="release_id" value={item.id} />
      <input type="hidden" name="expected_state_version" value={item.state_version} />
      <input type="hidden" name="command" value={command} />
      <label>{command === "approve" ? "审批说明" : "撤销原因"}<textarea name="reason" required={command === "revoke"} /></label>
    </ActionForm> : null}
  </div>;
}

function PromptBindingIdentity({ binding }: {
  binding: GeoWorkspaceData["promptBinding"]["data"];
}) {
  if (!binding || binding.status !== "bound") return <Empty>尚未绑定已批准 Prompt Release。</Empty>;
  return <div className={styles.keyValues}>
    <div><span className={styles.meta}>Skill</span><br /><strong>{binding.skill_key || "-"}</strong></div>
    <div><span className={styles.meta}>Skill Version ID</span><br /><code>{binding.skill_version_id}</code></div>
    <div><span className={styles.meta}>Release</span><br /><strong>v{binding.release_version}</strong></div>
    <div><span className={styles.meta}>Release ID</span><br /><code>{binding.template_release_id}</code></div>
    <div><span className={styles.meta}>Release hash</span><br /><code>{binding.release_hash}</code></div>
    <div><span className={styles.meta}>绑定记录</span><br /><strong>v{binding.binding_version}</strong><span className={styles.meta}>{binding.changed_by || "legacy actor unknown"} · {new Date(binding.changed_at).toLocaleString("zh-CN")}</span></div>
  </div>;
}

function readinessReasonLabel(value: string) {
  return ({
    prompt_binding_missing: "缺 Prompt 绑定", prompt_release_draft: "Prompt 未批准",
    prompt_release_revoked: "Prompt 已撤销", brief_missing: "缺 Brief",
    evidence_pack_missing: "缺 Evidence Pack", evidence_pack_not_ready: "Evidence Pack 未就绪",
    evidence_items_missing: "缺证据项", opportunity_blocked: "渠道任务受阻",
    destination_policy_missing: "缺政策复核", destination_policy_not_approved: "政策未批准"
  } as Record<string, string>)[value] || value;
}

function briefSummary(goals: GeoWorkspaceData["briefs"]["data"][number]["goals"]): string {
  const audience = typeof goals.audience === "string" ? goals.audience : "目标受众未填写";
  const intent = typeof goals.intent === "string" ? goals.intent : "内容目标未填写";
  const deliverable = typeof goals.deliverable === "string" ? goals.deliverable : "交付内容未填写";
  return `${audience} · ${intent} · ${deliverable}`;
}
