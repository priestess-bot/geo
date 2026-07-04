"use client";

import { useActionState, useState } from "react";

import {
  deleteMemberAction,
  createInvitationAction,
  createPortalTokenAction,
  importPromptsAction,
  invitationAction,
  projectLifecycleAction,
  revokePortalTokenAction,
  runFixtureE2EAction,
  saveBrandEntityAction,
  saveCompetitorEntityAction,
  saveLaunchConfigAction,
  saveMemberAction,
  savePromptAction,
  updateProjectAction,
  type ProjectActionState
} from "./actions";

const initialState: ProjectActionState = { ok: false };
const hydrationControlProps = { suppressHydrationWarning: true };

type RuntimeProjectRecord = {
  project: { id: string; name?: string; target_brand?: string; category?: string; status?: string };
  tenant?: { name?: string };
  brand?: {
    canonical_name?: string;
    official_domains?: string[];
    parent_company?: string | null;
    product_lines?: string[];
    status?: string;
  } | null;
};

type Competitor = {
  id?: string;
  canonical_name?: string;
  official_domains?: string[];
  parent_company?: string | null;
  product_lines?: string[];
  status?: string;
};

type PromptRecord = {
  id?: string;
  project_id?: string;
  market_code?: string;
  industry_code?: string;
  text?: string;
  intent_type?: string;
  city?: string;
  language?: string;
  target_brand?: string;
  competitors?: string[];
  priority?: number;
  intent_weight?: number | string;
  prompt_version?: string;
  status?: string;
};

type RuntimeListRecord = Record<string, unknown>;

function statusLabel(status?: string): string {
  const labels: Record<string, string> = {
    configured: "已配置",
    active: "运行中",
    paused: "已暂停",
    archived: "已归档",
    draft: "草稿",
    ready: "就绪",
    fixture: "开发测试",
    fixture_only: "仅开发测试",
    manual: "手工补录",
    manual_ready: "手工补录就绪",
    not_configured: "未配置",
    pending: "待处理",
    accepted: "已接受",
    revoked: "已撤销",
    expired: "已过期"
  };
  return labels[String(status || "").toLowerCase()] || status || "未知";
}

export function InvitationForm({ projectId, defaultEmail }: { projectId: string; defaultEmail?: string }) {
  const [state, formAction, pending] = useActionState(createInvitationAction, initialState);
  return (
    <form className="inlineForm" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <label><span>客户邮箱</span><input {...hydrationControlProps} name="email" type="email" defaultValue={defaultEmail || ""} placeholder="customer@example.com" required /></label>
      <button type="submit" disabled={pending}>{pending ? "创建中..." : "创建邀请"}</button>
      <ActionState state={state} />
    </form>
  );
}

export function ProjectLifecycleForm({ projectId, status }: { projectId: string; status?: string }) {
  const [state, formAction, pending] = useActionState(projectLifecycleAction, initialState);
  const isArchived = status === "archived";
  return (
    <form className="inlineForm compactForm" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <input {...hydrationControlProps} type="hidden" name="action" value={isArchived ? "restore" : "archive"} />
      <button
        type="submit"
        className={isArchived ? undefined : "danger"}
        disabled={pending}
        onClick={(event) => {
          if (!isArchived && !window.confirm("确认归档这个项目？归档不会物理删除数据，可在 archived 筛选中恢复。")) {
            event.preventDefault();
          }
        }}
      >
        {pending ? "处理中..." : isArchived ? "恢复项目" : "归档项目"}
      </button>
      <ActionState state={state} />
    </form>
  );
}

export function FixtureE2EForm({ projectId }: { projectId: string }) {
  const [state, formAction, pending] = useActionState(runFixtureE2EAction, initialState);
  return (
    <form className="configForm" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <label><span>Prompt 数量</span><input {...hydrationControlProps} name="prompt_limit" type="number" min={1} max={10} defaultValue={1} required /></label>
      <label><span>城市</span><input {...hydrationControlProps} name="cities" defaultValue="Sydney" required /></label>
      <label>
        <span>样本数</span>
        <select {...hydrationControlProps} name="sample_size" defaultValue="3">
          <option value="1">1</option>
          <option value="2">2</option>
          <option value="3">3</option>
        </select>
      </label>
      <input {...hydrationControlProps} type="hidden" name="persist_analysis" value="1" />
      <div className="formActions">
        <button type="submit" disabled={pending}>{pending ? "运行中..." : "运行本地全流程测试"}</button>
      </div>
      <ActionState state={state} />
    </form>
  );
}

export function ProjectBasicsForm({ record }: { record: RuntimeProjectRecord }) {
  const [state, formAction, pending] = useActionState(updateProjectAction, initialState);
  return (
    <form className="configForm" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={record.project.id} />
      <label><span>租户名称</span><input {...hydrationControlProps} name="tenant_name" defaultValue={record.tenant?.name || ""} required /></label>
      <label><span>项目名称</span><input {...hydrationControlProps} name="name" defaultValue={record.project.name || ""} required /></label>
      <label><span>目标品牌</span><input {...hydrationControlProps} name="target_brand" defaultValue={record.project.target_brand || ""} required /></label>
      <label><span>品类</span><input {...hydrationControlProps} name="category" defaultValue={record.project.category || ""} required /></label>
      <label>
        <span>项目状态</span>
        <select {...hydrationControlProps} name="status" defaultValue={record.project.status || "configured"}>
          <option value="configured">已配置</option>
          <option value="active">运行中</option>
          <option value="paused">已暂停</option>
          <option value="archived">已归档</option>
        </select>
      </label>
      <div className="formActions">
        <button type="submit" disabled={pending}>{pending ? "保存中..." : "保存基础配置"}</button>
      </div>
      <ActionState state={state} />
    </form>
  );
}

export function LaunchConfigForm({
  projectId,
  launch,
  competitors,
  scoreConfig,
  scoreFormulas
}: {
  projectId: string;
  launch: Record<string, unknown>;
  competitors: Competitor[];
  scoreConfig: Record<string, unknown> | null;
  scoreFormulas: Array<Record<string, unknown>>;
}) {
  const [state, formAction, pending] = useActionState(saveLaunchConfigAction, initialState);
  const competitorDomains = Array.isArray(launch.competitor_domains)
    ? launch.competitor_domains.join("\n")
    : competitors.flatMap((item) => item.official_domains || []).join("\n");
  const schedule = objectValue(launch.schedule);
  const connectors = objectValue(launch.external_connectors);
  const openaiConnector = objectValue(connectors.openai);
  const perplexityConnector = objectValue(connectors.perplexity);
  const googleConnector = objectValue(connectors.google_ai_mode);
  const scoringProfile = stringValue(launch.scoring_profile) || stringValue(scoreConfig?.formula_version) || "au_visibility_v1";
  const selectedFormula = scoreFormulas.find((formula) => stringValue(formula.formula_version) === scoringProfile);
  return (
    <form className="configForm" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <input {...hydrationControlProps} type="hidden" name="competitor_domains_snapshot" value={competitorDomains} />
      <label><span>客户邮箱</span><input {...hydrationControlProps} name="customer_email" type="email" defaultValue={stringValue(launch.customer_email)} required /></label>
      <label><span>主域名</span><input {...hydrationControlProps} name="primary_domain" defaultValue={stringValue(launch.primary_domain)} required /></label>
      <label><span>Locale</span><input {...hydrationControlProps} name="locale" defaultValue={stringValue(launch.locale) || "en-AU"} required /></label>
      <label><span>国家代码</span><input {...hydrationControlProps} name="country_code" defaultValue={stringValue(launch.country_code) || "AU"} required /></label>
      <label><span>时区</span><input {...hydrationControlProps} name="timezone" defaultValue={stringValue(launch.timezone) || "Australia/Sydney"} required /></label>
      <label>
        <span>采集模式</span>
        <select {...hydrationControlProps} name="collection_mode" defaultValue={stringValue(launch.collection_mode) || "api"}>
          <option value="api">真实 API</option>
          <option value="manual">手工补录</option>
        </select>
      </label>
      <label>
        <span>启动状态</span>
        <select {...hydrationControlProps} name="status" defaultValue={stringValue(launch.status) || "draft"}>
          <option value="draft">草稿</option>
          <option value="ready">就绪</option>
          <option value="active">运行中</option>
          <option value="paused">已暂停</option>
        </select>
      </label>
      <section className="wideField configBlock">
        <div className="sectionTitle">
          <div>
            <p className="eyebrow">评分配置</p>
            <h3>{scoringProfile}</h3>
          </div>
          <span className="statusPill">{stringValue(selectedFormula?.status) || "project"}</span>
        </div>
        <input {...hydrationControlProps} type="hidden" name="scoring_profile" value={scoringProfile} />
        <SummaryGrid rows={[
          ["配置记录", stringValue(scoreConfig?.id) || "系统默认公式"],
          ["公式版本", scoringProfile],
          ["配置来源", stringValue(scoreConfig?.updated_by) || "system-default"],
          ["更新时间", stringValue(scoreConfig?.updated_at) || "未写入项目级配置"],
          ["说明", stringValue(scoreConfig?.notes) || stringValue(selectedFormula?.description) || "默认 GEO 可见度评分配置"],
          ["权重合计", weightSummary(scoreConfig?.weights || selectedFormula?.weights)]
        ]} />
      </section>
      <section className="wideField configBlock">
        <div className="sectionTitle">
          <div>
            <p className="eyebrow">连接器配置</p>
            <h3>采集与回答源</h3>
          </div>
        </div>
        <p className="muted formIntro">这里不录入或回显密钥；凭证通过服务环境变量或外部密钥系统提供。</p>
        <div className="connectorGrid">
          <ConnectorConfigCard
            connector={openaiConnector}
            envDefault="OPENAI_API_KEY"
            keyPrefix="connector_openai"
            modeDefault="env"
            modelDefault="gpt-4.1-mini"
            name="OpenAI 连接器"
            statusDefault="not_configured"
          />
          <ConnectorConfigCard
            connector={perplexityConnector}
            envDefault="PERPLEXITY_API_KEY"
            keyPrefix="connector_perplexity"
            modeDefault="env"
            modelDefault="sonar"
            name="Perplexity 连接器"
            statusDefault="not_configured"
          />
          <ConnectorConfigCard
            connector={googleConnector}
            envDefault="GOOGLE_PLAYWRIGHT_ENABLED"
            keyPrefix="connector_google_ai_mode"
            modeDefault="manual_or_browser"
            modelDefault="google_ai_mode"
            name="Google AI Mode"
            statusDefault="manual_ready"
          />
        </div>
      </section>
      <details className="advancedField">
        <summary>高级配置：调度</summary>
        <div className="formGrid">
          <label>
            <span>调度频率</span>
            <select {...hydrationControlProps} name="schedule_cadence" defaultValue={stringValue(schedule.cadence) || "weekly"}>
              <option value="daily">每日</option>
              <option value="weekly">每周</option>
              <option value="monthly">每月</option>
            </select>
          </label>
          <label>
            <span>运行日</span>
            <select {...hydrationControlProps} name="schedule_weekday" defaultValue={stringValue(schedule.weekday) || "monday"}>
              <option value="monday">周一</option>
              <option value="tuesday">周二</option>
              <option value="wednesday">周三</option>
              <option value="thursday">周四</option>
              <option value="friday">周五</option>
              <option value="saturday">周六</option>
              <option value="sunday">周日</option>
            </select>
          </label>
        </div>
      </details>
      <div className="formActions">
        <button type="submit" disabled={pending}>{pending ? "保存中..." : "保存启动配置"}</button>
      </div>
      <ActionState state={state} />
    </form>
  );
}

export function BrandEntityForm({ projectId, brand, fallbackName }: { projectId: string; brand: RuntimeProjectRecord["brand"]; fallbackName?: string }) {
  const [state, formAction, pending] = useActionState(saveBrandEntityAction, initialState);
  return (
    <form className="configForm" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <label><span>品牌名称</span><input {...hydrationControlProps} name="canonical_name" defaultValue={brand?.canonical_name || fallbackName || ""} required /></label>
      <label><span>官网域名</span><textarea {...hydrationControlProps} name="official_domains" defaultValue={(brand?.official_domains || []).join("\n")} /></label>
      <label><span>母公司</span><input {...hydrationControlProps} name="parent_company" defaultValue={brand?.parent_company || ""} /></label>
      <label><span>产品线</span><textarea {...hydrationControlProps} name="product_lines" defaultValue={(brand?.product_lines || []).join("\n")} /></label>
      <label>
        <span>状态</span>
        <select {...hydrationControlProps} name="status" defaultValue={brand?.status || "active"}>
          <option value="active">运行中</option>
          <option value="paused">已暂停</option>
          <option value="archived">已归档</option>
        </select>
      </label>
      <div className="formActions">
        <button type="submit" disabled={pending}>{pending ? "保存中..." : "保存品牌配置"}</button>
      </div>
      <ActionState state={state} />
    </form>
  );
}

function ConnectorConfigCard({
  connector,
  envDefault,
  keyPrefix,
  modeDefault,
  modelDefault,
  name,
  statusDefault
}: {
  connector: Record<string, unknown>;
  envDefault: string;
  keyPrefix: string;
  modeDefault: string;
  modelDefault: string;
  name: string;
  statusDefault: string;
}) {
  const status = stringValue(connector.status) || statusDefault;
  return (
    <div className="connectorCard">
      <div className="sectionTitle">
        <h3>{name}</h3>
        <span className="statusPill">{statusLabel(status)}</span>
      </div>
      <label>
        <span>连接状态</span>
        <select {...hydrationControlProps} name={`${keyPrefix}_status`} defaultValue={status}>
          <option value="not_configured">未配置</option>
          <option value="configured">已配置</option>
          <option value="manual_ready">手工补录就绪</option>
          <option value="active">运行中</option>
          <option value="paused">已暂停</option>
        </select>
      </label>
      <label><span>运行模式</span><input {...hydrationControlProps} name={`${keyPrefix}_mode`} defaultValue={stringValue(connector.mode) || modeDefault} /></label>
      <label><span>模型 / 服务</span><input {...hydrationControlProps} name={`${keyPrefix}_model`} defaultValue={stringValue(connector.model) || modelDefault} /></label>
      <label><span>环境变量</span><input {...hydrationControlProps} name={`${keyPrefix}_env_var`} defaultValue={stringValue(connector.env_var) || envDefault} /></label>
      <label className="wideField"><span>备注</span><textarea {...hydrationControlProps} name={`${keyPrefix}_notes`} defaultValue={stringValue(connector.notes)} placeholder="记录测试状态、账号范围或手工采集说明。" /></label>
    </div>
  );
}

export function CompetitorEditor({ projectId, competitors }: { projectId: string; competitors: Competitor[] }) {
  const [draftCount, setDraftCount] = useState(0);
  const drafts = Array.from({ length: draftCount }, (_, index) => index);
  return (
    <div className="stack">
      {competitors.map((competitor, index) => (
        <details className="accordionItem" key={competitor.id || competitor.canonical_name}>
          <summary>
            <span>竞品 {index + 1} - {competitor.canonical_name || "未命名竞品"}</span>
            <small>{statusLabel(competitor.status)}</small>
          </summary>
          <CompetitorForm competitor={competitor} projectId={projectId} />
        </details>
      ))}
      {drafts.map((draftIndex) => (
        <details className="accordionItem addItem" key={`draft-${draftIndex}`} open>
          <summary>
            <span>竞品 {competitors.length + draftIndex + 1} - 未命名竞品</span>
            <small>待填写</small>
          </summary>
          <CompetitorForm projectId={projectId} />
        </details>
      ))}
      <div className="actionRow">
        <button type="button" className="secondary" onClick={() => setDraftCount((count) => count + 1)}>
          新增竞品
        </button>
      </div>
    </div>
  );
}

function CompetitorForm({ projectId, competitor }: { projectId: string; competitor?: Competitor }) {
  const [state, formAction, pending] = useActionState(saveCompetitorEntityAction, initialState);
  const isNew = !competitor?.id;
  return (
    <form className="configForm compactConfig" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <input {...hydrationControlProps} type="hidden" name="competitor_id" value={competitor?.id || ""} />
      <label><span>{isNew ? "新增竞品名称" : "竞品名称"}</span><input {...hydrationControlProps} name="canonical_name" defaultValue={competitor?.canonical_name || ""} required /></label>
      <label><span>域名</span><textarea {...hydrationControlProps} name="official_domains" defaultValue={(competitor?.official_domains || []).join("\n")} /></label>
      <label><span>母公司</span><input {...hydrationControlProps} name="parent_company" defaultValue={competitor?.parent_company || ""} /></label>
      <label><span>产品线</span><textarea {...hydrationControlProps} name="product_lines" defaultValue={(competitor?.product_lines || []).join("\n")} /></label>
      <label>
        <span>状态</span>
        <select {...hydrationControlProps} name="status" defaultValue={competitor?.status || "active"}>
          <option value="active">运行中</option>
          <option value="paused">已暂停</option>
          <option value="archived">已归档</option>
        </select>
      </label>
      <div className="formActions">
        <button type="submit" disabled={pending}>{pending ? "保存中..." : isNew ? "新增竞品" : "保存竞品"}</button>
      </div>
      <ActionState state={state} />
    </form>
  );
}

export function MemberManagement({ projectId }: { projectId: string }) {
  return (
    <div className="twoCol compact">
      <MemberSaveForm projectId={projectId} />
      <MemberDeleteForm projectId={projectId} />
    </div>
  );
}

export function InvitationList({ invitations, projectId }: { invitations: RuntimeListRecord[]; projectId: string }) {
  if (!invitations.length) {
    return <p className="muted emptyState">暂无邀请记录。</p>;
  }
  return (
    <div className="summaryList">
      {invitations.map((record) => {
        const invitation = objectValue(record.invitation);
        const invitationId = stringValue(invitation.id);
        const status = stringValue(invitation.status);
        return (
          <div className="summaryListRow" key={invitationId || stringValue(invitation.email)}>
            <div>
              <strong>{stringValue(invitation.email) || "未知邮箱"}</strong>
              <p className="muted">
                {stringValue(invitation.role) || "viewer"} · {statusLabel(status)} · {stringValue(invitation.created_at) || "无创建时间"}
              </p>
              <p className="muted">邀请 ID：{invitationId || "无"} · token hash：{shortValue(stringValue(invitation.invite_token_hash)) || "未生成"}</p>
            </div>
            {status === "pending" && invitationId ? <InvitationActionForm invitationId={invitationId} projectId={projectId} /> : null}
          </div>
        );
      })}
    </div>
  );
}

function InvitationActionForm({ invitationId, projectId }: { invitationId: string; projectId: string }) {
  const [state, formAction, pending] = useActionState(invitationAction, initialState);
  return (
    <form className="inlineForm compactForm" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <input {...hydrationControlProps} type="hidden" name="invitation_id" value={invitationId} />
      <input {...hydrationControlProps} type="hidden" name="action" value="revoke" />
      <button type="submit" className="danger" disabled={pending}>{pending ? "撤销中..." : "撤销邀请"}</button>
      <ActionState state={state} />
    </form>
  );
}

export function TokenList({ tokens }: { tokens: RuntimeListRecord[] }) {
  if (!tokens.length) {
    return <p className="muted emptyState">暂无门户 token。raw token 创建后只显示一次。</p>;
  }
  return (
    <div className="summaryList">
      {tokens.map((record) => {
        const token = objectValue(record.portal_token || record.token || record.customer_portal_token);
        const tokenId = stringValue(token.id) || stringValue(record.id);
        return (
          <div className="summaryListRow" key={tokenId}>
            <div>
              <strong>{tokenId || "未知 token"}</strong>
              <p className="muted">
                {stringValue(token.member_user_id) || stringValue(record.member_user_id) || "未知用户"} · {statusLabel(stringValue(token.status) || stringValue(record.status))}
              </p>
              <p className="muted">创建时间：{stringValue(token.created_at) || stringValue(record.created_at) || "无"}</p>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function MemberList({ members }: { members: RuntimeListRecord[] }) {
  if (!members.length) {
    return <p className="muted emptyState">暂无成员记录。</p>;
  }
  return (
    <div className="summaryList">
      {members.map((record) => {
        const member = objectValue(record.member);
        const memberId = stringValue(member.id) || stringValue(record.id) || stringValue(member.user_id);
        return (
          <div className="summaryListRow" key={memberId}>
            <div>
              <strong>{stringValue(member.user_id) || "未知用户"}</strong>
              <p className="muted">{stringValue(member.role) || "viewer"} · {stringValue(member.created_at) || "无创建时间"}</p>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function PromptEditor({ projectId, prompt }: { projectId: string; prompt: PromptRecord }) {
  const [editing, setEditing] = useState(false);
  const [state, formAction, pending] = useActionState(savePromptAction, initialState);
  return (
    <div className="promptRow">
      <div className="promptSummary">
        <strong>{prompt.text || "未命名 Prompt"}</strong>
        <span>{prompt.intent_type || "未设置"}</span>
        <span>{prompt.city || "未设置"}</span>
        <span>{statusLabel(prompt.status)}</span>
        <span>{String(prompt.priority ?? "")}</span>
        <button type="button" className="secondary" onClick={() => setEditing((value) => !value)}>
          {editing ? "收起" : "修改"}
        </button>
      </div>
      {editing ? (
        <form className="configForm compactConfig" action={formAction}>
          <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
          <input {...hydrationControlProps} type="hidden" name="prompt_id" value={prompt.id || ""} />
          <label className="wideField"><span>Prompt 文本</span><textarea {...hydrationControlProps} name="text" defaultValue={prompt.text || ""} required /></label>
          <label><span>Intent</span><input {...hydrationControlProps} name="intent_type" defaultValue={prompt.intent_type || "brand_awareness"} required /></label>
          <label><span>城市</span><input {...hydrationControlProps} name="city" defaultValue={prompt.city || "Sydney"} required /></label>
          <label><span>语言</span><input {...hydrationControlProps} name="language" defaultValue={prompt.language || "en-AU"} required /></label>
          <label><span>目标品牌</span><input {...hydrationControlProps} name="target_brand" defaultValue={prompt.target_brand || ""} required /></label>
          <label><span>优先级</span><input {...hydrationControlProps} name="priority" type="number" min={0} defaultValue={String(prompt.priority ?? 1)} required /></label>
          <label><span>Intent 权重</span><input {...hydrationControlProps} name="intent_weight" type="number" min={0.01} step={0.01} defaultValue={String(prompt.intent_weight ?? 1)} required /></label>
          <label><span>Prompt 版本</span><input {...hydrationControlProps} name="prompt_version" defaultValue={prompt.prompt_version || "au_dtc_ecommerce_v1"} required /></label>
          <label className="wideField"><span>竞品名称</span><textarea {...hydrationControlProps} name="competitors" defaultValue={(prompt.competitors || []).join("\n")} /></label>
          <label>
            <span>状态</span>
            <select {...hydrationControlProps} name="status" defaultValue={prompt.status || "active"}>
              <option value="active">运行中</option>
              <option value="paused">已暂停</option>
              <option value="archived">已归档</option>
            </select>
          </label>
          <div className="formActions">
            <button type="submit" disabled={pending}>{pending ? "保存中..." : "保存 Prompt"}</button>
          </div>
          <ActionState state={state} />
        </form>
      ) : null}
    </div>
  );
}

function MemberSaveForm({ projectId }: { projectId: string }) {
  const [state, formAction, pending] = useActionState(saveMemberAction, initialState);
  return (
    <form className="inlineForm" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <label><span>用户 ID / 邮箱</span><input {...hydrationControlProps} name="user_id" placeholder="customer@example.com" required /></label>
      <label>
        <span>角色</span>
        <select {...hydrationControlProps} name="role" defaultValue="viewer">
          <option value="owner">owner</option>
          <option value="admin">admin</option>
          <option value="analyst">analyst</option>
          <option value="viewer">viewer</option>
        </select>
      </label>
      <button type="submit" disabled={pending}>{pending ? "保存中..." : "保存成员"}</button>
      <ActionState state={state} />
    </form>
  );
}

function MemberDeleteForm({ projectId }: { projectId: string }) {
  const [state, formAction, pending] = useActionState(deleteMemberAction, initialState);
  return (
    <form className="inlineForm" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <label><span>用户 ID / 邮箱</span><input {...hydrationControlProps} name="user_id" placeholder="customer@example.com" required /></label>
      <button type="submit" className="danger" disabled={pending}>{pending ? "删除中..." : "删除成员"}</button>
      <ActionState state={state} />
    </form>
  );
}

export function PromptImportForm({ projectId, promptLimit }: { projectId: string; promptLimit: number }) {
  const [state, formAction, pending] = useActionState(importPromptsAction, initialState);
  return (
    <form className="configForm singleColumn" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <input {...hydrationControlProps} type="hidden" name="prompt_limit" value={String(promptLimit)} />
      {state.error ? <p className="muted errorText">{state.error}</p> : null}
      <label><span>最大导入行数</span><input {...hydrationControlProps} name="max_rows" type="number" min={1} max={200} defaultValue={100} /></label>
      <label>
        <span>CSV 内容</span>
        <textarea
          {...hydrationControlProps}
          name="csv_content"
          placeholder={"text,intent_type,city,language,priority\nIs Koala visible in AI answers?,brand_awareness,Sydney,en-AU,10"}
          required
        />
      </label>
      <div className="formActions">
        <button type="submit" disabled={pending}>{pending ? "导入中..." : "导入 Prompt CSV"}</button>
      </div>
      {!state.error ? <ActionState state={state} /> : null}
    </form>
  );
}

export function TokenCreateForm({ projectId }: { projectId: string }) {
  const [state, formAction, pending] = useActionState(createPortalTokenAction, initialState);
  return (
    <form className="inlineForm" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <label><span>viewer user id</span><input {...hydrationControlProps} name="member_user_id" placeholder="customer@example.com" required /></label>
      <label><span>invitation id</span><input {...hydrationControlProps} name="invitation_id" placeholder="可选" /></label>
      <button type="submit" disabled={pending}>{pending ? "生成中..." : "生成 token"}</button>
      <ActionState state={state} />
    </form>
  );
}

export function TokenRevokeForm({ projectId }: { projectId: string }) {
  const [state, formAction, pending] = useActionState(revokePortalTokenAction, initialState);
  return (
    <form className="inlineForm" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <label><span>token id</span><input {...hydrationControlProps} name="token_id" placeholder="customer_portal_token id" required /></label>
      <button type="submit" disabled={pending}>{pending ? "撤销中..." : "撤销 token"}</button>
      <ActionState state={state} />
    </form>
  );
}

function ActionState({ state }: { state: ProjectActionState }) {
  if (state.error) {
    return <p className="muted errorText">{state.error}</p>;
  }
  if (!state.ok) {
    return null;
  }
  return (
    <div className="actionResult">
      {state.message ? <p>{state.message}</p> : null}
      {state.details?.length ? (
        <div className="summaryTable">
          {state.details.map(([label, value]) => (
            <div key={`${label}-${value}`}>
              <span>{label}</span>
              <strong>{value}</strong>
            </div>
          ))}
        </div>
      ) : null}
      {state.rawToken ? <p>raw portal token：<code>{state.rawToken}</code></p> : null}
      {state.rawInviteToken ? <p>raw invite token：<code>{state.rawInviteToken}</code></p> : null}
      {state.inviteUrl ? <a className="button secondary" href={state.inviteUrl}>打开客户邀请入口</a> : null}
    </div>
  );
}

function SummaryGrid({ rows }: { rows: Array<[string, string]> }) {
  return (
    <div className="summaryGrid compactSummaryGrid">
      {rows.map(([label, value]) => (
        <div className="summaryItem" key={`${label}-${value}`}>
          <span>{label}</span>
          <strong>{value || "无"}</strong>
        </div>
      ))}
    </div>
  );
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function weightSummary(value: unknown): string {
  const weights = objectValue(value);
  const entries = Object.entries(weights);
  if (!entries.length) {
    return "未配置";
  }
  const total = entries.reduce((sum, [, weight]) => sum + (typeof weight === "number" ? weight : Number(weight) || 0), 0);
  return `${entries.length} 项 · 合计 ${total.toFixed(2)}`;
}

function shortValue(value: string): string {
  if (!value) {
    return "";
  }
  return value.length > 14 ? `${value.slice(0, 10)}...${value.slice(-4)}` : value;
}
