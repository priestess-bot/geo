"use client";

import { useActionState } from "react";

import { createProjectAction, type CreateProjectActionState } from "./actions";

const initialState: CreateProjectActionState = { ok: false };

export default function CreateProjectForm() {
  const [state, formAction, pending] = useActionState(createProjectAction, initialState);
  return (
    <form className="wizard" action={formAction}>
      {state.error ? (
        <section className="notice error">
          <strong>创建失败</strong>
          <span>{state.error}</span>
        </section>
      ) : null}
      {state.ok && state.projectId ? (
        <section className="notice success">
          <strong>项目已创建</strong>
          <span>{state.projectName || state.projectId}</span>
          <div className="actionRow">
            <a className="button" href={`/projects/${encodeURIComponent(state.projectId)}`}>打开项目详情</a>
            {state.inviteUrl ? <a className="button secondary" href={state.inviteUrl}>打开客户邀请入口</a> : null}
          </div>
          {state.rawInviteToken ? (
            <p className="muted">邀请 token 只显示一次：<code>{state.rawInviteToken}</code></p>
          ) : null}
        </section>
      ) : null}

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
          <label><span>项目名称</span><input name="project_name" placeholder="AU GEO Pilot" /></label>
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
          <label><span>目标品牌</span><input name="target_brand" placeholder="ExampleBrand" required /></label>
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
          <label><span>竞品名称</span><textarea name="competitors" placeholder={"Competitor A\nCompetitor B\nCompetitor C"} required /></label>
          <label><span>竞品域名</span><textarea name="competitor_domains" placeholder={"competitor-a.com\ncompetitor-b.com\ncompetitor-c.com"} /></label>
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
          <label><span>采集模式</span><select name="collection_mode"><option value="fixture">fixture</option><option value="api">api</option></select></label>
          <label><span>启动状态</span><select name="launch_status"><option value="draft">draft</option><option value="ready">ready</option><option value="active">active</option></select></label>
          <label><span>调度配置 JSON</span><textarea name="schedule" placeholder='{"cadence":"weekly"}' /></label>
          <label><span>连接器配置 JSON</span><textarea name="external_connectors" placeholder='{"openai":{"status":"configured"}}' /></label>
        </div>
        <div className="testRow">
          <span className="muted">提交会调用 POST /v1/projects/runtime/au/dtc-ecommerce。</span>
          <button type="submit" disabled={pending}>{pending ? "创建中..." : "创建项目"}</button>
        </div>
      </section>
    </form>
  );
}
