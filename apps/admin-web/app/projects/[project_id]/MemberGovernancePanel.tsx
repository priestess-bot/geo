"use client";

import { AddMemberForm } from "./AddMemberForm";
import { MemberRow } from "./MemberRow";
import type { ProjectMemberLoadResult } from "./memberTypes";
import styles from "./MemberGovernance.module.css";

export function MemberGovernancePanel({
  data,
  projectId
}: {
  data: ProjectMemberLoadResult;
  projectId: string;
}) {
  const activeMembers = data.page.items.filter((member) => member.status === "active");
  const revokedMembers = data.page.items.filter((member) => member.status === "revoked");
  const activeOwnerCount = activeMembers.filter((member) => member.role === "owner").length;
  const activeManagerCount = activeMembers.filter(
    (member) => member.role === "owner" || member.role === "admin"
  ).length;
  const canManage = data.currentRole === "owner" || data.currentRole === "admin";
  const actorRole = data.currentRole;

  return (
    <section className={styles.panel} aria-labelledby="member-governance-title">
      <header className={styles.panelHeader}>
        <div>
          <p>成员权限</p>
          <h3 id="member-governance-title">内部 OIDC 成员</h3>
        </div>
        <div className={styles.summary}>
          <span><strong>{activeMembers.length}</strong> 当前页有效</span>
          <span><strong>{revokedMembers.length}</strong> 当前页已撤销</span>
          <span><strong>{data.page.total}</strong> 全部成员</span>
          <span><strong>{data.currentRole ? roleName(data.currentRole) : "未识别"}</strong> 当前角色</span>
        </div>
      </header>

      {data.problem ? (
        <div className={styles.loadError} role="alert">
          <strong>{problemTitle(data.problem.status)}</strong>
          <span>{data.problem.detail}</span>
          {data.problem.correlationId ? <small>关联 ID：{data.problem.correlationId}</small> : null}
        </div>
      ) : null}

      {canManage && actorRole ? (
        <AddMemberForm
          actorRole={actorRole}
          idempotencyKey={data.commandKeys.add}
          projectId={projectId}
        />
      ) : null}

      {!data.problem && data.page.items.length === 0 ? (
        <div className={styles.emptyState}>
          <strong>暂无成员记录</strong>
        </div>
      ) : null}

      {canManage && actorRole && data.page.items.length ? (
        <div className={styles.memberList}>
          {data.page.items.map((member) => {
            const keys = data.commandKeys.byMembership[member.membership_id];
            return keys ? (
              <MemberRow
                key={member.membership_id}
                activeManagerCount={activeManagerCount}
                activeOwnerCount={activeOwnerCount}
                actorId={data.actorId}
                actorRole={actorRole}
                commandKeys={keys}
                member={member}
                projectId={projectId}
              />
            ) : null;
          })}
        </div>
      ) : null}
    </section>
  );
}

function roleName(role: "owner" | "admin" | "analyst"): string {
  if (role === "owner") return "负责人";
  if (role === "admin") return "管理员";
  return "分析师";
}

function problemTitle(status: number | undefined): string {
  if (status === 403) return "无权管理成员";
  if (status === 409) return "成员状态冲突";
  if (status === 422) return "成员数据无效";
  return "成员列表加载失败";
}
