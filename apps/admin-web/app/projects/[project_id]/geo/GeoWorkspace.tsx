"use client";

import { useActionState } from "react";

import {
  approveGeoQuery,
  createGeoCampaign,
  createGeoDestination,
  createGeoOpportunity,
  createGeoProduct,
  createGeoPromptTemplate,
  createGeoPromptVersion,
  createGeoQuery,
  createGeoSubmission,
  generateGeoPackage,
  importGeoObservation,
  publishGeoPromptTemplate,
  qualifyGeoDestination,
  reviewGeoPackage,
  reviewGeoPublisher,
  reviseGeoPackage,
  setGeoPublishedUrl,
  submitGeoPackageReview,
  verifyGeoPublishedUrl
} from "./actions";

type RecordItem = Record<string, unknown>;
type Page = { records: RecordItem[] };
type ActionResult = { error?: string };
const initial: ActionResult = {};

function text(record: RecordItem, key: string): string { return String(record[key] || ""); }

function downloadPackage(item: RecordItem): void {
  const title = text(item, "title").replace(/[^a-z0-9]+/gi, "-").replace(/(^-|-$)/g, "") || "geo-placement-package";
  const status = text(item, "status");
  const evidence = Array.isArray(item.evidence_snapshot) ? item.evidence_snapshot : [];
  const claims = Array.isArray(item.claim_inventory) ? item.claim_inventory : [];
  const manifest = `Status: ${status}\nContent hash: ${text(item,"content_hash")}\nPrompt bundle hash: ${text(item,"prompt_bundle_hash")}\nEvidence sources: ${evidence.map((record) => text(record as RecordItem,"source_url")).join(", ")}\n\nClaim inventory:\n${JSON.stringify(claims,null,2)}`;
  const body = [status === "approved" ? "APPROVED FOR MANUAL USE" : "DRAFT - NOT APPROVED FOR USE", text(item, "title"), manifest, text(item, "rendered_text"), text(item, "disclosure_text")]
    .filter(Boolean)
    .join("\n\n");
  const blob = new Blob([body], { type: "text/markdown;charset=utf-8" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `${title}${status === "approved" ? "" : ".DRAFT"}.md`;
  link.style.display = "none";
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(link.href), 1_000);
}

function State({ state }: { state: ActionResult }) {
  return state.error ? <p className="formError">{state.error}</p> : null;
}

function ProductForm({ projectId }: { projectId: string }) {
  const [state, action, pending] = useActionState(createGeoProduct, initial);
  return <form action={action} className="configForm singleColumn compactForm">
    <input type="hidden" name="project_id" value={projectId} />
    <h3>添加投放商品</h3>
    <label><span>商品名称</span><input name="name" required placeholder="TerraMow V600" /></label>
    <label><span>官方产品 URL</span><input name="canonical_url" type="url" required placeholder="https://..." /></label>
    <div className="twoCol compact noTopMargin"><label><span>品类</span><input name="category" required placeholder="robotic lawn mower" /></label><label><span>市场</span><input name="market_code" defaultValue="AU" required /></label></div>
    <label><span>已批准事实摘要</span><textarea name="facts" required placeholder="仅填写可由官方 URL 或已批准证据支撑的信息" /></label>
    <button type="submit" disabled={pending}>{pending ? "保存中..." : "添加商品"}</button><State state={state} />
  </form>;
}

function CampaignForm({ products, projectId }: { products: RecordItem[]; projectId: string }) {
  const [state, action, pending] = useActionState(createGeoCampaign, initial);
  return <form action={action} className="configForm singleColumn compactForm">
    <input type="hidden" name="project_id" value={projectId} /><h3>创建 Campaign</h3>
    <label><span>主商品</span><select name="product_id" required defaultValue=""><option value="" disabled>选择商品</option>{products.map((item) => <option key={text(item, "id")} value={text(item, "id")}>{text(item, "name")}</option>)}</select></label>
    <label><span>Campaign 名称</span><input name="name" required placeholder="TerraMow V600 AU Recommendation" /></label>
    <label><span>禁止 Claim</span><textarea name="forbidden_claims" placeholder="每行一条，例如 guaranteed recommendation" /></label>
    <input type="hidden" name="market_code" value="AU" /><button type="submit" disabled={pending || products.length === 0}>{pending ? "创建中..." : "创建 Campaign"}</button><State state={state} />
  </form>;
}

function QueryForm({ campaigns, projectId }: { campaigns: RecordItem[]; projectId: string }) {
  const [state, action, pending] = useActionState(createGeoQuery, initial);
  return <form action={action} className="configForm singleColumn compactForm">
    <input type="hidden" name="project_id" value={projectId} /><h3>添加消费者查询</h3>
    <label><span>Campaign</span><select name="campaign_id" required defaultValue=""><option value="" disabled>选择 Campaign</option>{campaigns.map((item) => <option key={text(item, "id")} value={text(item, "id")}>{text(item, "name")}</option>)}</select></label>
    <label><span>真实消费者问法</span><textarea name="query_text" required placeholder="What robotic lawn mower is suitable for..." /></label>
    <label><span>观察平台</span><select name="platform" defaultValue="chatgpt_search"><option value="chatgpt_search">ChatGPT Search</option><option value="google">Google</option></select></label>
    <button type="submit" disabled={pending || campaigns.length === 0}>{pending ? "保存中..." : "提交查询建议"}</button><State state={state} />
  </form>;
}

function DestinationForm({ projectId, publishers }: { projectId: string; publishers: RecordItem[] }) {
  const [state, action, pending] = useActionState(createGeoDestination, initial);
  return <form action={action} className="configForm singleColumn compactForm">
    <input type="hidden" name="project_id" value={projectId} /><h3>建立渠道投放任务</h3>
    <label><span>渠道</span><select name="publisher_id" required defaultValue=""><option value="" disabled>选择渠道</option>{publishers.map((item) => <option key={text(item, "id")} value={text(item, "id")}>{text(item, "canonical_domain")}</option>)}</select></label>
    <label><span>任务名称</span><input name="name" required placeholder="Official disclosed participation" /></label>
    <label><span>具体目的地 URL / 账号</span><input name="destination_url" type="url" required placeholder="https://..." /></label>
    <div className="twoCol compact noTopMargin"><label><span>任务类型</span><select name="task_type" defaultValue="owned_content"><option value="owned_content">自有内容</option><option value="marketplace_listing">商城资料</option><option value="video_content">视频内容</option><option value="social_content">社媒内容</option><option value="business_profile">商家资料</option><option value="official_community_participation">披露官方社区参与</option><option value="deal_submission">优惠提交</option><option value="expert_answer">披露专业回答</option></select></label><label><span>Task Key</span><input name="task_key" required placeholder="placement.reddit.disclosed_official_post" /></label></div>
    <label><span>账号/关系类型</span><select name="ownership_kind" defaultValue="owned"><option value="owned">自有账号/站点</option><option value="marketplace_authorized">授权卖家</option><option value="community_official">披露官方身份</option><option value="deal_platform">优惠平台商家</option><option value="knowledge_contributor">披露贡献者</option></select></label>
    <label><span>渠道规则与披露说明</span><textarea name="policy_notes" required placeholder="记录人工审核的规则、允许方式和披露要求" /></label>
    <button type="submit" disabled={pending}>{pending ? "保存中..." : "创建候选任务"}</button><State state={state} />
  </form>;
}

function PublisherReviewForm({ projectId, publishers }: { projectId: string; publishers: RecordItem[] }) {
  const [state, action, pending] = useActionState(reviewGeoPublisher, initial);
  return <form action={action} className="configForm singleColumn compactForm"><input type="hidden" name="project_id" value={projectId}/><h3>复核渠道政策</h3><label><span>渠道</span><select name="publisher_id" required defaultValue=""><option value="" disabled>选择渠道</option>{publishers.map((item) => <option key={text(item,"id")} value={text(item,"id")}>{text(item,"canonical_domain")} · {text(item,"status")}</option>)}</select></label><label><span>复核结论</span><select name="status" defaultValue="approved"><option value="approved">允许合规人工内容</option><option value="restricted">证据或授权不足</option><option value="prohibited">禁止使用</option></select></label><label><span>已复核规则</span><textarea name="reviewed_rules" required/></label><label><span>身份要求</span><textarea name="identity_requirement" required defaultValue="Use an authorised and disclosed brand identity"/></label><button type="submit" disabled={pending}>保存政策复核</button><State state={state}/></form>;
}

function ChannelMatrix({ destinations, publishers }: { destinations: RecordItem[]; publishers: RecordItem[] }) {
  return <div className="detailPanel spacedPanel"><p className="eyebrow">九渠道覆盖</p><h3>渠道准备度</h3><div className="list">{publishers.map((publisher) => { const destination=destinations.find((item) => text(item,"publisher_id") === text(publisher,"id")); return <div className="listItem" key={text(publisher,"id")}><strong>{text(publisher,"canonical_domain")}</strong><span className="muted">Policy {text(publisher,"status")} · Destination {destination ? text(destination,"qualification_status") : "missing"} · {destination ? text(destination,"task_key") : "等待真实授权/上下文"}</span></div>; })}</div></div>;
}

function ObservationForm({ observations, projectId, queries }: { observations: RecordItem[]; projectId: string; queries: RecordItem[] }) {
  const [state, action, pending] = useActionState(importGeoObservation, initial);
  return <form action={action} className="configForm singleColumn compactForm">
    <input type="hidden" name="project_id" value={projectId} /><h3>导入基线/复测观察</h3>
    <label><span>已批准查询</span><select name="campaign_query_id" required defaultValue=""><option value="" disabled>选择已批准查询</option>{queries.filter((item) => text(item, "status") === "approved").map((item) => <option key={text(item, "id")} value={text(item, "id")}>{text(item, "platform")} · {text(item, "query_text")}</option>)}</select></label>
    <div className="twoCol compact noTopMargin"><label><span>阶段</span><select name="observation_phase" defaultValue="baseline"><option value="baseline">baseline</option><option value="retest">retest</option></select></label><label><span>样本编号</span><input name="sample_index" type="number" min="1" defaultValue="1" required /></label></div>
    <label><span>原始回答/结果</span><textarea name="raw_answer" required /></label><label><span>引用 URL</span><textarea name="citation_urls" placeholder="每行一条公开引用 URL" /></label><label><span>截图或导出工件 URL</span><input name="artifact_url" type="url" /></label><label><span>可见模型/界面版本</span><input name="visible_model" placeholder="例如 ChatGPT Search" /></label>
    <button type="submit" disabled={pending || !queries.some((item) => text(item, "status") === "approved")}>{pending ? "导入中..." : "保存观察样本"}</button><State state={state} />
    {observations.length ? <p className="muted">当前 Campaign 已保存 {observations.length} 条观察样本。</p> : null}
  </form>;
}

function PlacementWorkflow({
  campaigns, destinations, measurements, opportunities, packages, promptTemplates, projectId, queries, submissions
}: {
  campaigns: RecordItem[]; destinations: RecordItem[]; measurements: RecordItem[]; opportunities: RecordItem[];
  packages: RecordItem[]; promptTemplates: RecordItem[]; projectId: string; queries: RecordItem[]; submissions: RecordItem[];
}) {
  const [opportunityState, opportunityAction, opportunityPending] = useActionState(createGeoOpportunity, initial);
  const [templateState, templateAction, templatePending] = useActionState(createGeoPromptTemplate, initial);
  const [versionState, versionAction, versionPending] = useActionState(createGeoPromptVersion, initial);
  const [publishState, publishAction, publishPending] = useActionState(publishGeoPromptTemplate, initial);
  const [packageState, packageAction, packagePending] = useActionState(generateGeoPackage, initial);
  const [reviewState, reviewAction, reviewPending] = useActionState(submitGeoPackageReview, initial);
  const [decisionState, decisionAction, decisionPending] = useActionState(reviewGeoPackage, initial);
  const [revisionState, revisionAction, revisionPending] = useActionState(reviseGeoPackage, initial);
  const [submissionState, submissionAction, submissionPending] = useActionState(createGeoSubmission, initial);
  const [urlState, urlAction, urlPending] = useActionState(setGeoPublishedUrl, initial);
  const [verifyState, verifyAction, verifyPending] = useActionState(verifyGeoPublishedUrl, initial);
  const versions = promptTemplates.flatMap((template) => Array.isArray(template.versions) ? template.versions as RecordItem[] : []);
  return <>
    <div className="twoCol compact">
      <form action={opportunityAction} className="configForm singleColumn compactForm"><input type="hidden" name="project_id" value={projectId}/><h3>创建投放 Opportunity</h3><label><span>Campaign</span><select name="campaign_id" required defaultValue=""><option value="" disabled>选择 Campaign</option>{campaigns.map((item) => <option key={text(item,"id")} value={text(item,"id")}>{text(item,"name")}</option>)}</select></label><label><span>已审核 Destination</span><select name="destination_id" required defaultValue=""><option value="" disabled>选择 Destination</option>{destinations.filter((item) => text(item,"qualification_status") === "approved").map((item) => <option key={text(item,"id")} value={text(item,"id")}>{text(item,"name")}</option>)}</select></label><label><span>关联查询</span><select name="campaign_query_id" defaultValue=""><option value="">无</option>{queries.filter((item) => text(item,"status") === "approved").map((item) => <option key={text(item,"id")} value={text(item,"id")}>{text(item,"query_text")}</option>)}</select></label><label><span>任务标题</span><input name="title" required/></label><label><span>投放理由</span><textarea name="rationale" required/></label><input type="hidden" name="priority" value="high"/><button type="submit" disabled={opportunityPending}>创建 Opportunity</button><State state={opportunityState}/></form>
      <form action={templateAction} className="configForm singleColumn compactForm"><input type="hidden" name="project_id" value={projectId}/><h3>新建独立 Prompt</h3><label><span>Task Key</span><input name="task_key" required placeholder="placement.reddit.disclosed_official_post"/></label><label><span>名称</span><input name="name" required/></label><button type="submit" disabled={templatePending}>保存 Prompt 定义</button><State state={templateState}/></form>
    </div>
    <div className="twoCol compact">
      <form action={versionAction} className="configForm singleColumn compactForm"><input type="hidden" name="project_id" value={projectId}/><h3>Prompt 版本</h3><label><span>Prompt 定义</span><select name="template_id" required defaultValue=""><option value="" disabled>选择定义</option>{promptTemplates.map((item) => <option key={text(item,"id")} value={text(item,"id")}>{text(item,"task_key")} · {text(item,"status")}</option>)}</select></label><label><span>System Prompt</span><textarea name="system_template" required/></label><label><span>User Prompt</span><textarea name="user_template" required/></label><input type="hidden" name="version_number" value="1"/><button type="submit" disabled={versionPending}>保存草稿版本</button><State state={versionState}/></form>
      <form action={publishAction} className="configForm singleColumn compactForm"><input type="hidden" name="project_id" value={projectId}/><h3>发布 Prompt</h3><label><span>Prompt 定义</span><select name="template_id" required defaultValue=""><option value="" disabled>选择定义</option>{promptTemplates.map((item) => <option key={text(item,"id")} value={text(item,"id")}>{text(item,"task_key")} · {text(item,"status")}</option>)}</select></label><p className="muted">发布会使该定义和草稿版本可供文案包使用；旧包仍保留其历史版本。</p><button type="submit" disabled={publishPending}>发布 Prompt</button><State state={publishState}/></form>
    </div>
    <form action={packageAction} className="configForm singleColumn"><input type="hidden" name="project_id" value={projectId}/><p className="eyebrow">DeepSeek 文案生成</p><h3>从已审核证据生成渠道文案包</h3><div className="twoCol compact noTopMargin"><label><span>Opportunity</span><select name="opportunity_id" required defaultValue=""><option value="" disabled>选择 Opportunity</option>{opportunities.map((item) => <option key={text(item,"id")} value={text(item,"id")}>{text(item,"title")} · {text(item,"task_type")}</option>)}</select></label><label><span>已发布 Prompt Version</span><select name="prompt_template_version_id" required defaultValue=""><option value="" disabled>选择版本</option>{versions.filter((item) => text(item,"status") === "published").map((item) => <option key={text(item,"id")} value={text(item,"id")}>v{text(item,"version_number")} · {text(item,"prompt_template_id")}</option>)}</select></label></div><label><span>幂等键</span><input name="idempotency_key" required minLength={8} placeholder="qc-run-channel-v1"/></label><label><span>证据 URL</span><input name="evidence_url" type="url" required/></label><label><span>证据原文/已批准事实</span><textarea name="evidence_text" required/></label><div className="twoCol compact noTopMargin"><label><span>来源类型</span><select name="source_kind" defaultValue="brand_authored"><option value="brand_authored">品牌官方</option><option value="editorial">独立编辑来源</option><option value="verified_experience">真实使用描述</option></select></label><label><span>使用权</span><select name="usage_rights" defaultValue="owned"><option value="owned">品牌自有</option><option value="licensed">已许可</option><option value="public_reference">允许公开引用</option></select></label></div><div className="twoCol compact noTopMargin"><label><span>事实主体</span><input name="subject" required placeholder="TerraMow V600"/></label><label><span>主体角色</span><select name="subject_role" defaultValue="primary_product"><option value="primary_product">主产品</option><option value="primary_brand">主品牌</option><option value="competitor">竞品</option><option value="market">市场</option><option value="neutral">中立主体</option></select></label></div><label><span>公开披露文本</span><textarea name="disclosure_text" required defaultValue="Disclosure: I am posting on behalf of the brand."/></label><label><span>禁止 Claim</span><textarea name="forbidden_claims" placeholder="每行一条"/></label><button type="submit" disabled={packagePending}>{packagePending ? "正在调用 DeepSeek..." : "生成并保存文案包"}</button><State state={packageState}/></form>
    <div className="twoCol compact">
      <form action={reviewAction} className="configForm singleColumn compactForm"><input type="hidden" name="project_id" value={projectId}/><h3>提交文案审核</h3><label><span>Draft 文案包</span><select name="package_id" required defaultValue=""><option value="" disabled>选择 Draft</option>{packages.filter((item) => ["draft","needs_revision"].includes(text(item,"status"))).map((item) => <option key={text(item,"id")} value={text(item,"id")}>{text(item,"title")}</option>)}</select></label><button type="submit" disabled={reviewPending}>提交给独立 Reviewer</button><State state={reviewState}/></form>
      <form action={decisionAction} className="configForm singleColumn compactForm"><input type="hidden" name="project_id" value={projectId}/><h3>独立 Reviewer 决定</h3><label><span>待审核文案包</span><select name="package_id" required defaultValue=""><option value="" disabled>选择待审核包</option>{packages.filter((item) => text(item,"status") === "pending_review").map((item) => <option key={text(item,"id")} value={text(item,"id")}>{text(item,"title")}</option>)}</select></label><label><span>决定</span><select name="decision" defaultValue="approved"><option value="approved">批准待人工使用</option><option value="needs_revision">退回修改</option><option value="blocked">阻断</option></select></label><label><span>质控分数</span><input name="qc_score" type="number" min="0" max="100" defaultValue="85" required/></label><label><span>质控报告</span><textarea name="review_notes" required placeholder="记录事实、Claim、披露和渠道适配结论"/></label><label><span><input type="checkbox" name="claim_inventory_complete" /> 我已确认 Claim 清单覆盖全部事实性陈述</span></label><p className="muted">必须使用与提交者不同的 Reviewer 账户；服务端会拒绝自审、低于 85 分和未确认清单的批准。</p><button type="submit" disabled={decisionPending}>保存审核决定</button><State state={decisionState}/></form>
    </div>
    <form action={revisionAction} className="configForm singleColumn compactForm"><input type="hidden" name="project_id" value={projectId}/><h3>创建修订版本</h3><label><span>基础文案包</span><select name="package_id" required defaultValue="" onChange={(event) => { const item=packages.find((candidate) => text(candidate,"id") === event.target.value); const form=event.currentTarget.form; if(item&&form){(form.elements.namedItem("base_content_hash") as HTMLInputElement).value=text(item,"content_hash");(form.elements.namedItem("rendered_text") as HTMLTextAreaElement).value=text(item,"rendered_text");(form.elements.namedItem("claim_inventory") as HTMLTextAreaElement).value=JSON.stringify(item.claim_inventory,null,2);}}}><option value="" disabled>选择需修订文案</option>{packages.filter((item) => ["needs_revision","approved","draft"].includes(text(item,"status"))).map((item) => <option key={text(item,"id")} value={text(item,"id")}>{text(item,"title")} · v{text(item,"version_number")}</option>)}</select></label><input type="hidden" name="base_content_hash"/><label><span>修订正文</span><textarea name="rendered_text" required/></label><label><span>Claim Inventory JSON</span><textarea name="claim_inventory" required/></label><label><span>修改原因</span><textarea name="reason" required/></label><button type="submit" disabled={revisionPending}>保存新版本并重新质控</button><State state={revisionState}/></form>
    <div className="detailPanel spacedPanel"><p className="eyebrow">文案包预览与导出</p><h3>导出不代表发布</h3>{packages.length ? packages.map((item) => { const claims=Array.isArray(item.claim_inventory) ? item.claim_inventory as RecordItem[] : []; return <article key={text(item,"id")} className="detailPanel spacedPanel"><p><strong>{text(item,"title")}</strong> · {text(item,"status")} · QA {text(item,"qa_status")} · {text(item,"generation_model") || "manual compile"}</p><pre className="muted">{text(item,"rendered_text")}</pre><p className="muted">{text(item,"disclosure_text")}</p><p className="muted">Prompt Bundle {text(item,"prompt_bundle_hash") || "legacy"} · Content {text(item,"content_hash")}</p>{claims.map((claim,index) => <p key={`${text(item,"id")}-claim-${index}`}><strong>Claim:</strong> {text(claim,"text")} · {text(claim,"support_status")}</p>)}<button type="button" onClick={() => downloadPackage(item)}>下载 Markdown 文案包</button></article>; }) : <p className="muted">生成后可在此处审阅和下载文案包。下载不会创建投放记录。</p>}</div>
    {false ? <><div className="twoCol compact">
      <form action={submissionAction} className="configForm singleColumn compactForm"><input type="hidden" name="project_id" value={projectId}/><h3>记录人工投放</h3><label><span>已批准文案包</span><select name="package_id" required defaultValue=""><option value="" disabled>选择已批准包</option>{packages.filter((item) => text(item,"status") === "approved").map((item) => <option key={text(item,"id")} value={text(item,"id")}>{text(item,"title")}</option>)}</select></label><label><span>提交截图/工件 URL</span><input name="submission_evidence_url" type="url"/></label><label><span>外部平台编号</span><input name="external_reference"/></label><label><span>说明</span><textarea name="notes"/></label><button type="submit" disabled={submissionPending}>记录人工提交</button><State state={submissionState}/></form>
    </div>
    <div className="twoCol compact">
      <form action={urlAction} className="configForm singleColumn compactForm"><input type="hidden" name="project_id" value={projectId}/><h3>回填公开 URL</h3><label><span>已提交任务</span><select name="submission_id" required defaultValue=""><option value="" disabled>选择 Submission</option>{submissions.filter((item) => text(item,"status") === "submitted").map((item) => <option key={text(item,"id")} value={text(item,"id")}>{text(item,"package_title")}</option>)}</select></label><label><span>公开 URL</span><input name="published_url" type="url" required/></label><button type="submit" disabled={urlPending}>回填 URL</button><State state={urlState}/></form>
      <form action={verifyAction} className="configForm singleColumn compactForm"><input type="hidden" name="project_id" value={projectId}/><h3>实时公开验证</h3><label><span>待验证 Submission</span><select name="submission_id" required defaultValue=""><option value="" disabled>选择待验证项</option>{submissions.filter((item) => text(item,"status") === "published_url_pending_verification").map((item) => <option key={text(item,"id")} value={text(item,"id")}>{text(item,"published_url")}</option>)}</select></label><p className="muted">仅抓取与已审核 Destination 同主机的 HTTPS URL，并检查正文片段和披露文本。</p><button type="submit" disabled={verifyPending}>执行公开验证</button><State state={verifyState}/></form>
    </div>
    <div className="detailPanel spacedPanel"><p className="eyebrow">测量窗口</p><h3>仅已验证发布可进入效果测量</h3>{measurements.length ? measurements.map((item) => <p key={text(item,"id")}><strong>{text(item,"window_key")}</strong> · {text(item,"status")} · due {text(item,"due_at")}</p>) : <p className="muted">暂无测量窗口。公开 URL 通过验证后自动创建 T+28、T+56、T+84。</p>}</div></> : <div className="detailPanel spacedPanel"><p className="eyebrow">发布功能未启用</p><h3>本轮交付停在 approved</h3><p className="muted">人工提交、URL 验证和效果测量不在本轮验收范围，当前工作区不会创建新的 Submission。</p></div>}
  </>;
}

export function GeoWorkspace({ campaigns, destinations, measurements, observations, opportunities, packages, products, promptTemplates, publishers, queries, projectId, submissions }: { campaigns: Page; destinations: Page; measurements: Page; observations: Page; opportunities: Page; packages: Page; products: Page; promptTemplates: Page; publishers: Page; queries: Page; projectId: string; submissions: Page }) {
  const [approveState, approveAction, approvePending] = useActionState(approveGeoQuery, initial);
  const [qualifyState, qualifyAction, qualifyPending] = useActionState(qualifyGeoDestination, initial);
  return <section className="detailPanel unframedPanel">
    <div className="sectionTitle"><div><p className="eyebrow">GEO Placement v3</p><h2>Campaign 到人工投放闭环</h2></div></div>
    <p className="muted formIntro">此工作区只创建人工投放任务；不会自动登录或发帖。导出不等于发布，只有公开 URL 经验证才进入有效覆盖。</p>
    <div className="twoCol compact"><ProductForm projectId={projectId} /><CampaignForm products={products.records} projectId={projectId} /></div>
    <ChannelMatrix destinations={destinations.records} publishers={publishers.records}/>
    <div className="twoCol compact"><QueryForm campaigns={campaigns.records} projectId={projectId} /><PublisherReviewForm projectId={projectId} publishers={publishers.records}/></div>
    <DestinationForm projectId={projectId} publishers={publishers.records} />
    <ObservationForm observations={observations.records} projectId={projectId} queries={queries.records} />
    <div className="twoCol compact">
      <div className="detailPanel spacedPanel"><p className="eyebrow">Campaign</p><h3>当前 Campaign</h3>{campaigns.records.map((item) => <p key={text(item,"id")}><strong>{text(item,"name")}</strong><br /><span className="muted">{text(item,"product_name")} · {text(item,"status")}</span></p>) || <p className="muted">尚未创建 Campaign。</p>}</div>
      <div className="detailPanel spacedPanel"><p className="eyebrow">查询审批</p><h3>待审批消费者查询</h3>{queries.records.map((item) => <div key={text(item,"id")}><p><strong>{text(item,"query_text")}</strong><br /><span className="muted">{text(item,"platform")} · {text(item,"status")}</span></p>{text(item,"status") === "suggested" ? <form action={approveAction}><input type="hidden" name="project_id" value={projectId}/><input type="hidden" name="query_id" value={text(item,"id")}/><button type="submit" disabled={approvePending}>批准并冻结观察条件</button></form> : null}</div>)}<State state={approveState} /></div>
    </div>
    <div className="detailPanel spacedPanel"><p className="eyebrow">渠道任务</p><h3>Destination 资格审核</h3>{destinations.records.map((item) => <div key={text(item,"id")}><strong>{text(item,"name")}</strong><p className="muted">{text(item,"canonical_domain")} · {text(item,"task_key")} · {text(item,"qualification_status")}</p>{text(item,"qualification_status") === "candidate" ? <form action={qualifyAction}><input type="hidden" name="project_id" value={projectId}/><input type="hidden" name="destination_id" value={text(item,"id")}/><button type="submit" disabled={qualifyPending}>审核通过渠道任务</button></form> : null}</div>)}<State state={qualifyState} /></div>
    <PlacementWorkflow campaigns={campaigns.records} destinations={destinations.records} measurements={measurements.records} opportunities={opportunities.records} packages={packages.records} promptTemplates={promptTemplates.records} projectId={projectId} queries={queries.records} submissions={submissions.records} />
  </section>;
}
