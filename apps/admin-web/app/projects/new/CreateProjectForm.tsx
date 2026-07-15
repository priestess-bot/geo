"use client";

import { useActionState } from "react";

import {
  createProjectAction,
  initialCreateProjectState
} from "./actions";

export default function CreateProjectForm() {
  const [state, action, pending] = useActionState(
    createProjectAction,
    initialCreateProjectState
  );
  return (
    <section className="panel" style={{ marginTop: 18 }}>
      <form className="configForm" action={action}>
        <div className="sectionTitle">
          <div>
            <p className="eyebrow">项目边界</p>
            <h2>创建 Catalog 项目</h2>
          </div>
        </div>
        <label className="wideField">
          <span>项目名称</span>
          <input
            name="name"
            maxLength={200}
            placeholder="例如：Acme Australia GEO"
            required
            disabled={pending || state.kind === "success"}
          />
        </label>
        <div className="notice">
          <strong>创建范围</strong>
          <span>本操作只创建项目及当前身份的初始项目权限，不会自动生成客户邀请、测试数据或运行配置。</span>
        </div>
        <div className="actionRow">
          <button type="submit" disabled={pending || state.kind === "success"}>
            {pending ? "创建中..." : "创建项目"}
          </button>
          {state.project ? (
            <a className="button secondary" href={`/projects/${encodeURIComponent(state.project.id)}`}>
              打开项目详情
            </a>
          ) : null}
        </div>
        {state.kind !== "idle" ? (
          <div className={`notice ${state.kind === "error" ? "error" : "success"}`} role={state.kind === "error" ? "alert" : "status"}>
            <strong>{state.kind === "error" ? "创建失败" : state.project?.name}</strong>
            <span>{state.message}</span>
            {state.correlationId ? <small>关联 ID：{state.correlationId}</small> : null}
          </div>
        ) : null}
      </form>
    </section>
  );
}
