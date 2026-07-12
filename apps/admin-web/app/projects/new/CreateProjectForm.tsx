"use client";

import { useActionState, useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import { createProjectAction, type CreateProjectActionState } from "./actions";

const initialState: CreateProjectActionState = { ok: false };

type DraftSummary = {
  tenantName: string;
  projectName: string;
  targetBrand: string;
  category: string;
  marketCode: string;
  marketName: string;
  locale: string;
  timezone: string;
  currency: string;
  primaryLanguage: string;
  cities: string[];
  industryCode: string;
  industryName: string;
  brandOfficialDomains: string[];
  brandParentCompany: string;
  brandProductLines: string[];
  competitors: string[];
  competitorDomains: string[];
  customerEmail: string;
  ownerUserId: string;
  collectionMode: string;
};

const emptySummary: DraftSummary = {
  tenantName: "",
  projectName: "",
  targetBrand: "",
  category: "",
  marketCode: "GLOBAL",
  marketName: "Global",
  locale: "en",
  timezone: "UTC",
  currency: "USD",
  primaryLanguage: "English",
  cities: [],
  industryCode: "dtc_ecommerce",
  industryName: "DTC / e-commerce",
  brandOfficialDomains: [],
  brandParentCompany: "",
  brandProductLines: [],
  competitors: [],
  competitorDomains: [],
  customerEmail: "",
  ownerUserId: "",
  collectionMode: "api"
};

export default function CreateProjectForm() {
  const [state, formAction, pending] = useActionState(createProjectAction, initialState);
  const [modalOpen, setModalOpen] = useState(false);
  const [confirmedSubmit, setConfirmedSubmit] = useState(false);
  const [summary, setSummary] = useState<DraftSummary>(emptySummary);
  const [competitorRows, setCompetitorRows] = useState(() => [0, 1, 2]);
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
      ["租户名称", summary.tenantName || "客户组织"],
      ["项目名称", summary.projectName || "客户品牌 GEO 项目"],
      ["目标品牌", summary.targetBrand || "客户品牌"],
      ["品类", summary.category || "产品与服务"],
      ["市场", `${summary.marketName} (${summary.marketCode})`],
      ["语言区域", summary.locale],
      ["时区", summary.timezone],
      ["币种", summary.currency],
      ["主要语言", summary.primaryLanguage],
      ["目标城市", joinValues(summary.cities)],
      ["行业", `${summary.industryName} (${summary.industryCode})`],
      ["官网域名", joinValues(summary.brandOfficialDomains)],
      ["母公司", summary.brandParentCompany || "未填写"],
      ["产品线", joinValues(summary.brandProductLines)],
      ["竞品名称", joinValues(summary.competitors)],
      ["竞品域名", joinValues(summary.competitorDomains)],
      ["客户邮箱", summary.customerEmail || "未填写"],
      ["项目负责人", summary.ownerUserId || "runtime-console"],
      ["采集模式", summary.collectionMode],
      ["初始状态", "暂停中（完成 Prompt 与连接器配置后可启动）"]
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
          <label><span>租户名称</span><input name="tenant_name" placeholder="客户组织" required /></label>
          <label><span>项目名称</span><input name="project_name" placeholder="客户品牌 GEO 项目" /></label>
        </div>
      </section>

      <section className="step">
        <div className="stepHeader">
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <span className="stepIndex">2</span>
            <div>
              <h2>市场与行业</h2>
              <p className="muted">这些字段决定语言、时区、报告口径和后续 Prompt 的地域范围。</p>
            </div>
          </div>
        </div>
        <div className="formGrid">
          <label><span>市场代码</span><input name="market_code" defaultValue="GLOBAL" required /></label>
          <label><span>市场名称</span><input name="market_name" defaultValue="Global" required /></label>
          <label><span>语言区域</span><input name="locale" defaultValue="en" required /></label>
          <label><span>时区</span><input name="timezone" defaultValue="UTC" required /></label>
          <label><span>币种</span><input name="currency" defaultValue="USD" required /></label>
          <label><span>主要语言</span><input name="primary_language" defaultValue="English" required /></label>
          <label><span>行业代码</span><input name="industry_code" defaultValue="dtc_ecommerce" required /></label>
          <label><span>行业名称</span><input name="industry_name" defaultValue="DTC / e-commerce" required /></label>
          <label className="fullWidth"><span>目标城市</span><input name="cities" placeholder="可选，用逗号分隔，例如 Shanghai, Singapore" /></label>
        </div>
      </section>

      <section className="step">
        <div className="stepHeader">
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <span className="stepIndex">3</span>
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
          <label><span>产品线</span><input name="brand_product_lines" placeholder="用逗号分隔" /></label>
        </div>
      </section>

      <section className="step">
        <div className="stepHeader">
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <span className="stepIndex">4</span>
            <div>
            <h2>竞品范围</h2>
              <p className="muted">首期要求 3 到 5 个竞品，减少评分和对比维度漂移。</p>
            </div>
          </div>
        </div>
        <div className="competitorInputGrid">
          {competitorRows.map((row, index) => (
            <div className="competitorInputRow" key={row}>
              <label>
                <span>竞品 {index + 1} 名称</span>
                <input name="competitor_name" placeholder={`竞品 ${index + 1}`} required={index < 3} suppressHydrationWarning />
              </label>
              <label>
                <span>竞品 {index + 1} 域名</span>
                <input name="competitor_domain" placeholder={`competitor-${index + 1}.com`} suppressHydrationWarning />
              </label>
              <button
                type="button"
                className="secondary compactIconButton"
                disabled={competitorRows.length <= 3}
                onClick={() => setCompetitorRows((rows) => rows.filter((item) => item !== row))}
              >
                删除
              </button>
            </div>
          ))}
          <button
            type="button"
            className="secondary addCompetitorButton"
            disabled={competitorRows.length >= 5}
            onClick={() => setCompetitorRows((rows) => [...rows, Math.max(...rows) + 1])}
          >
            添加新竞品
          </button>
        </div>
      </section>

      <section className="step">
        <div className="stepHeader">
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <span className="stepIndex">5</span>
            <div>
              <h2>客户入口</h2>
              <p className="muted">客户邮箱用于生成一次性邀请；客户首次兑换后建立安全会话，后续访问不再在 URL 中携带 token。</p>
            </div>
          </div>
        </div>
        <div className="formGrid">
          <label><span>客户邮箱</span><input name="customer_email" type="email" placeholder="customer@example.com" required /></label>
          <label><span>项目负责人</span><input name="owner_user_id" placeholder="runtime-console" /></label>
        </div>
      </section>

      <section className="step">
        <div className="stepHeader">
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <span className="stepIndex">6</span>
            <div>
              <h2>采集与外部调用</h2>
              <p className="muted">项目创建后保持暂停；Prompt 和连接器满足启动条件后，可在项目看板中启动。</p>
            </div>
          </div>
          <span className="statusPill">Runtime API</span>
        </div>
        <div className="formGrid">
          <label><span>采集模式</span><select name="collection_mode" defaultValue="api"><option value="api">真实 API</option><option value="manual">手工补录</option></select></label>
          <div className="notice">
            <strong>初始状态：暂停中</strong>
            <span>启动前必须至少有一条启用的 Prompt，并有可用连接器或已配置手工补录。</span>
          </div>
        </div>
        <div className="testRow">
          <span className="muted">提交后创建项目、品牌、竞品、启动配置和客户邀请。</span>
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
    marketCode: value(formData, "market_code"),
    marketName: value(formData, "market_name"),
    locale: value(formData, "locale"),
    timezone: value(formData, "timezone"),
    currency: value(formData, "currency"),
    primaryLanguage: value(formData, "primary_language"),
    cities: lines(value(formData, "cities")),
    industryCode: value(formData, "industry_code"),
    industryName: value(formData, "industry_name"),
    brandOfficialDomains: lines(value(formData, "brand_official_domains")),
    brandParentCompany: value(formData, "brand_parent_company"),
    brandProductLines: lines(value(formData, "brand_product_lines")),
    competitors: formData.getAll("competitor_name").map((item) => String(item || "").trim()).filter(Boolean),
    competitorDomains: formData.getAll("competitor_domain").map((item) => String(item || "").trim()).filter(Boolean),
    customerEmail: value(formData, "customer_email"),
    ownerUserId: value(formData, "owner_user_id"),
    collectionMode: value(formData, "collection_mode") || "api"
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
