import { randomUUID } from "node:crypto";

import CreateProjectForm from "./CreateProjectForm";

export default function NewProjectPage() {
  return (
    <main className="shell">
      <section className="topbar">
        <div>
          <p className="eyebrow">项目创建向导</p>
          <h1>新建 GEO 项目</h1>
          <p className="muted" style={{ marginTop: 8 }}>
            按步骤填完核心信息后，后台会创建项目、启动配置、品牌默认配置、评分权重和客户查看邀请。
          </p>
        </div>
        <nav className="nav">
          <a className="button secondary" href="/projects">项目列表</a>
          <a className="button secondary" href="/">返回首页</a>
        </nav>
      </section>

      <CreateProjectForm invitationIdempotencyKey={`project-invitation-${randomUUID()}`} />
    </main>
  );
}
