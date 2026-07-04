"use client";

import { useActionState, useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import { createProjectAction, type CreateProjectActionState } from "./actions";

const initialState: CreateProjectActionState = { ok: false };

type DraftSummary = {
  tenantName: string;
  projectName: string;
  targetBrand: string;
  category: string;
  brandOfficialDomains: string[];
  brandParentCompany: string;
  competitors: string[];
  competitorDomains: string[];
  customerEmail: string;
  ownerUserId: string;
  collectionMode: string;
  launchStatus: string;
  schedule: string;
  externalConnectors: string;
};

const emptySummary: DraftSummary = {
  tenantName: "",
  projectName: "",
  targetBrand: "",
  category: "",
  brandOfficialDomains: [],
  brandParentCompany: "",
  competitors: [],
  competitorDomains: [],
  customerEmail: "",
  ownerUserId: "",
  collectionMode: "api",
  launchStatus: "draft",
  schedule: "",
  externalConnectors: ""
};

export default function CreateProjectForm() {
  const [state, formAction, pending] = useActionState(createProjectAction, initialState);
  const [modalOpen, setModalOpen] = useState(false);
  const [confirmedSubmit, setConfirmedSubmit] = useState(false);
  const [summary, setSummary] = useState<DraftSummary>(emptySummary);
  const [clientError, setClientError] = useState("");
  const confirmedSubmitRef = useRef(false);
  const submitButtonRef = useRef<HTMLButtonElement>(null);
  const modalTitleId = "create-project-confirm-title";
  const canEdit = !pending && !state.ok;
  const modalMode = state.ok ? "success" : "confirm";

  useEffect(() => {
    if (state.ok || state.error) {
      setModalOpen(true);
      setConfirmedSubmit(false);
    }
  }, [state]);

  const summaryRows = useMemo(
    () => [
      ["租户名称", summary.tenantName || "Design Partner AU"],
      ["项目名称", summary.projectName || "客户品牌 GEO 项目"],
      ["目标品牌", summary.targetBrand || "客户品牌"],
      ["品类", summary.category || "DTC ecommerce products"],
      ["官网域名", joinValues(summary.brandOfficialDomains)],
      ["母公司", summary.brandParentCompany || "未填写"],
      ["竞品名称", joinValues(summary.competitors)],
      ["竞品域名", joinValues(summary.competitorDomains)],
      ["客户邮箱", summary.customerEmail || "未填写"],
      ["项目 owner", summary.ownerUserId || "runtime-console"],
      ["采集模式", summary.collectionMode],
      ["启动状态", summary.launchStatus],
      ["调度配置 JSON", summary.schedule || "{}"],
      ["连接器配置 JSON", summary.externalConnectors || "{}"]
    ],
    [summary]
  );

  function handleReview(event: FormEvent<HTMLFormElement>) {
    if (confirmedSubmitRef.current) {
      confirmedSubmitRef.current = false;
      setConfirmedSubmit(false);
      return;
    }
    event.preventDefault();
    const form = event.currentTarget;
    if (!form.reportValidity()) {
      return;
    }
    const formData = new FormData(form);
    const nextSummary = buildSummary(formData);
    if (nextSummary.competitors.length < 3 || nextSummary.competitors.length > 5) {
      setClientError("竞品名称需要填写 3 到 5 个。");
      setSummary(nextSummary);
      setModalOpen(true);
      return;
    }
    const jsonError = firstJsonObjectError(nextSummary.schedule, "调度配置 JSON")
      || firstJsonObjectError(nextSummary.externalConnectors, "连接器配置 JSON");
    if (jsonError) {
      setClientError(jsonError);
      setSummary(nextSummary);
      setModalOpen(true);
      return;
    }
    setClientError("");
    setSummary(nextSummary);
    setModalOpen(true);
  }

  function handleConfirmSubmit() {
    confirmedSubmitRef.current = true;
    setConfirmedSubmit(true);
    setClientError("");
    window.requestAnimationFrame(() => submitButtonRef.current?.click());
  }

  function handleEdit() {
    setModalOpen(false);
    setClientError("");
  }

  return (
    <form className="wizard" action={formAction} onSubmit={handleReview}>
      <button ref={submitButtonRef} type="submit" className="visuallyHidden" tabIndex={-1} aria-hidden="true">
        确认提交
      </button>

      <section className="step">
        <div className="stepHeader">
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <span className="stepIndex">1</span>
            <div>
              <h2>租户与项目</h2>
              <p className="muted">确定内部归属和客户可见项目名称。</p>
            </div>
          </div>
        </div>
        <div className="formGrid">
          <label><span>租户名称</span><input name="tenant_name" placeholder="Design Partner AU" /></label>
          <label><span>项目名称</span><input name="project_name" placeholder="客户品牌 GEO 项目" /></label>
        </div>
      </section>

      <section className="step">
        <div className="stepHeader">
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <span className="stepIndex">2</span>
            <div>
              <h2>品牌与官网</h2>
              <p className="muted">主域名会写入启动配置，并作为客户门户默认展示字段。</p>
            </div>
          </div>
          <span className="statusPill">提交前校验</span>
        </div>
        <div className="formGrid">
          <label><span>目标品牌</span><input name="target_brand" placeholder="客户品牌" required /></label>
          <label><span>品类</span><input name="category" placeholder="DTC ecommerce products" required /></label>
          <label><span>官网域名</span><input name="brand_official_domains" placeholder="example.com" required /></label>
          <label><span>母公司</span><input name="brand_parent_company" placeholder="可选" /></label>
        </div>
      </section>

      <section className="step">
        <div className="stepHeader">
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <span className="stepIndex">3</span>
            <div>
              <h2>竞品范围</h2>
              <p className="muted">首期要求 3 到 5 个竞品，减少评分和对比维度漂移。</p>
            </div>
          </div>
        </div>
        <div className="formGrid">
          <label><span>竞品名称</span><textarea name="competitors" placeholder={"Competitor A\nCompetitor B\nCompetitor C"} required suppressHydrationWarning /></label>
          <label><span>竞品域名</span><textarea name="competitor_domains" placeholder={"competitor-a.com\ncompetitor-b.com\ncompetitor-c.com"} suppressHydrationWarning /></label>
        </div>
      </section>

      <section className="step">
        <div className="stepHeader">
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <span className="stepIndex">4</span>
            <div>
              <h2>客户入口</h2>
              <p className="muted">客户邮箱用于生成 viewer 邀请；客户首次用邀请链接换取门户 token。</p>
            </div>
          </div>
        </div>
        <div className="formGrid">
          <label><span>客户邮箱</span><input name="customer_email" type="email" placeholder="customer@example.com" required /></label>
          <label><span>项目 owner</span><input name="owner_user_id" placeholder="runtime-console" /></label>
        </div>
      </section>

      <section className="step">
        <div className="stepHeader">
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <span className="stepIndex">5</span>
            <div>
              <h2>采集与外部调用</h2>
              <p className="muted">涉及外部调用的配置只保存状态和参数，不保存 raw secret。</p>
            </div>
          </div>
          <span className="statusPill">Runtime API</span>
        </div>
        <div className="formGrid">
          <label><span>采集模式</span><select name="collection_mode" defaultValue="api"><option value="api">真实 API</option><option value="manual">手工补录</option></select></label>
          <label><span>启动状态</span><select name="launch_status"><option value="draft">draft</option><option value="ready">ready</option><option value="active">active</option></select></label>
          <label><span>调度配置 JSON</span><textarea name="schedule" placeholder='{"cadence":"weekly"}' suppressHydrationWarning /></label>
          <label><span>连接器配置 JSON</span><textarea name="external_connectors" placeholder='{"openai":{"status":"configured"}}' suppressHydrationWarning /></label>
        </div>
        <div className="testRow">
          <span className="muted">提交会调用 POST /v1/projects/runtime/au/dtc-ecommerce。</span>
          <button type="submit" disabled={pending || state.ok}>{pending ? "创建中..." : "创建项目"}</button>
        </div>
      </section>

      {modalOpen ? (
        <div className="modalOverlay" role="presentation">
          <section
            aria-labelledby={modalTitleId}
            aria-modal="true"
            className="modalPanel"
            role="dialog"
          >
            {modalMode === "success" && state.projectId ? (
              <>
                <div className="modalHeader">
                  <div>
                    <p className="eyebrow">项目创建完成</p>
                    <h2 id={modalTitleId}>项目已创建</h2>
                  </div>
                  <span className="statusPill">已写入 Runtime</span>
                </div>
                <div className="notice success">
                  <strong>{state.projectName || state.projectId}</strong>
                  <span>项目 ID：<code>{state.projectId}</code></span>
                  {state.rawInviteToken ? (
                    <span>邀请 token 只显示一次：<code>{state.rawInviteToken}</code></span>
                  ) : null}
                </div>
                <div className="modalActions">
                  <a className="button" href={`/projects/${encodeURIComponent(state.projectId)}`}>打开项目详情</a>
                  {state.inviteUrl ? <a className="button secondary" href={state.inviteUrl}>打开客户邀请入口</a> : null}
                </div>
              </>
            ) : (
              <>
                <div className="modalHeader">
                  <div>
                    <p className="eyebrow">提交前确认</p>
                    <h2 id={modalTitleId}>确认项目信息</h2>
                  </div>
                  <span className="statusPill">{pending ? "创建中" : "待确认"}</span>
                </div>
                <div className="summaryGrid">
                  {summaryRows.map(([label, value]) => (
                    <div className="summaryItem" key={label}>
                      <span>{label}</span>
                      <strong>{value}</strong>
                    </div>
                  ))}
                </div>
                {clientError || state.error ? (
                  <div className="notice error">
                    <strong>需要修改后再提交</strong>
                    <span>{clientError || state.error}</span>
                  </div>
                ) : null}
                <div className="modalActions">
                  <button type="button" className="secondary" onClick={handleEdit} disabled={!canEdit}>返回修改</button>
                  <button type="button" onClick={handleConfirmSubmit} disabled={pending || Boolean(clientError)}>
                    {pending ? "创建中..." : "确认创建项目"}
                  </button>
                </div>
              </>
            )}
          </section>
        </div>
      ) : null}
    </form>
  );
}

function buildSummary(formData: FormData): DraftSummary {
  return {
    tenantName: value(formData, "tenant_name"),
    projectName: value(formData, "project_name"),
    targetBrand: value(formData, "target_brand"),
    category: value(formData, "category"),
    brandOfficialDomains: lines(value(formData, "brand_official_domains")),
    brandParentCompany: value(formData, "brand_parent_company"),
    competitors: lines(value(formData, "competitors")),
    competitorDomains: lines(value(formData, "competitor_domains")),
    customerEmail: value(formData, "customer_email"),
    ownerUserId: value(formData, "owner_user_id"),
    collectionMode: value(formData, "collection_mode") || "api",
    launchStatus: value(formData, "launch_status") || "draft",
    schedule: value(formData, "schedule"),
    externalConnectors: value(formData, "external_connectors")
  };
}

function value(formData: FormData, key: string): string {
  return String(formData.get(key) || "").trim();
}

function lines(raw: string): string[] {
  return raw
    .split(/\r?\n|,/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function joinValues(values: string[]): string {
  return values.length > 0 ? values.join(", ") : "未填写";
}

function firstJsonObjectError(raw: string, fieldName: string): string {
  const value = raw.trim();
  if (!value) {
    return "";
  }
  try {
    const parsed = JSON.parse(value) as unknown;
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? ""
      : `${fieldName} 必须是 JSON object。`;
  } catch {
    return `${fieldName} 不是合法 JSON。`;
  }
}
