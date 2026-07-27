"use client";

import { useActionState } from "react";

import {
  changeProjectMemberRoleAction,
  reactivateProjectMemberAction,
  revokeProjectMemberAction
} from "./memberActions";
import { MemberActionFeedback } from "./MemberActionFeedback";
import {
  initialMemberActionState,
  managedMemberRoles,
  type ManagedMemberRole,
  type ProjectMemberSummary
} from "./memberTypes";
import styles from "./MemberGovernance.module.css";

const roleLabels: Record<ManagedMemberRole, string> = {
  owner: "负责人",
  admin: "管理员",
  analyst: "分析师 / 审核员"
};

type RowKeys = Readonly<{
  changeRole: string;
  reactivate: string;
  revoke: string;
}>;

export function MemberRow({
  activeManagerCount,
  activeOwnerCount,
  actorId,
  actorRole,
  commandKeys,
  member,
  projectId
}: {
  activeManagerCount: number;
  activeOwnerCount: number;
  actorId: string;
  actorRole: ManagedMemberRole;
  commandKeys: RowKeys;
  member: ProjectMemberSummary;
  projectId: string;
}) {
  const [roleState, roleAction, rolePending] = useActionState(
    changeProjectMemberRoleAction,
    initialMemberActionState
  );
  const [revokeState, revokeAction, revokePending] = useActionState(
    revokeProjectMemberAction,
    initialMemberActionState
  );
  const [reactivateState, reactivateAction, reactivatePending] = useActionState(
    reactivateProjectMemberAction,
    initialMemberActionState
  );
  const isActive = member.status === "active";
  const isSelf = member.subject === actorId;
  const targetIsOwner = member.role === "owner";
  const canTargetRole = actorRole === "owner" || !targetIsOwner;
  const isLastOwner = targetIsOwner && activeOwnerCount <= 1;
  const isLastSelfManager = isSelf
    && (member.role === "owner" || member.role === "admin")
    && activeManagerCount <= 1;
  const canChangeRole = isActive && canTargetRole && !isLastOwner && !isLastSelfManager;
  const canRevoke = isActive && canTargetRole && !isLastOwner && !isLastSelfManager;
  const canReactivate = !isActive && canTargetRole;
  const allowedRoles = actorRole === "owner"
    ? managedMemberRoles
    : managedMemberRoles.filter((role) => role !== "owner");
  const commandPending = rolePending || revokePending || reactivatePending;

  return (
    <article className={styles.memberRow}>
      <div className={styles.identityCell}>
        <div className={styles.memberHeading}>
          <strong>{member.display_name}</strong>
          {isSelf ? <span className={styles.selfBadge}>当前账号</span> : null}
        </div>
        {member.email ? (
          <a href={`mailto:${member.email}`}>{member.email}</a>
        ) : (
          <span>系统身份（无登录邮箱）</span>
        )}
        <span>{member.issuer}</span>
        <code>{member.subject}</code>
      </div>
      <div className={styles.stateCell}>
        <span className={member.status === "active" ? styles.activeBadge : styles.revokedBadge}>
          {member.status === "active" ? "有效" : "已撤销"}
        </span>
        <strong>{roleLabels[member.role]}</strong>
        <small>{formatCreatedAt(member.created_at)}</small>
      </div>
      <div className={styles.rowActions}>
        {isActive ? (
          <>
            <form action={roleAction} className={styles.roleForm}>
              <CommandFields
                idempotencyKey={commandKeys.changeRole}
                membershipId={member.membership_id}
                projectId={projectId}
              />
              <label>
                <span className={styles.srOnly}>调整 {member.display_name} 的角色</span>
                <select name="role" defaultValue={member.role} disabled={!canChangeRole || commandPending}>
                  {allowedRoles.map((role) => (
                    <option key={role} value={role}>{roleLabels[role]}</option>
                  ))}
                </select>
              </label>
              <button
                type="submit"
                className="secondary"
                disabled={!canChangeRole || commandPending}
                title={canChangeRole ? "保存角色" : blockedReason(isLastOwner, isLastSelfManager, canTargetRole)}
              >
                {rolePending ? "保存中..." : "保存角色"}
              </button>
            </form>
            <form action={revokeAction}>
              <CommandFields
                idempotencyKey={commandKeys.revoke}
                membershipId={member.membership_id}
                projectId={projectId}
              />
              <button
                type="submit"
                className="danger"
                disabled={!canRevoke || commandPending}
                title={canRevoke ? "撤销项目访问" : blockedReason(isLastOwner, isLastSelfManager, canTargetRole)}
                onClick={(event) => {
                  if (!window.confirm(`确认撤销 ${member.display_name} 的项目访问？`)) {
                    event.preventDefault();
                  }
                }}
              >
                {revokePending ? "撤销中..." : "撤销"}
              </button>
            </form>
          </>
        ) : (
          <form action={reactivateAction}>
            <CommandFields
              idempotencyKey={commandKeys.reactivate}
              membershipId={member.membership_id}
              projectId={projectId}
            />
            <button
              type="submit"
              disabled={!canReactivate || commandPending}
              title={canReactivate ? "恢复项目访问" : "只有负责人可以恢复负责人角色"}
            >
              {reactivatePending ? "恢复中..." : "恢复访问"}
            </button>
          </form>
        )}
      </div>
      <div className={styles.feedbackRow}>
        <MemberActionFeedback state={roleState} />
        <MemberActionFeedback state={revokeState} />
        <MemberActionFeedback state={reactivateState} />
      </div>
    </article>
  );
}

function CommandFields({
  idempotencyKey,
  membershipId,
  projectId
}: {
  idempotencyKey: string;
  membershipId: string;
  projectId: string;
}) {
  return (
    <>
      <input type="hidden" name="project_id" value={projectId} />
      <input type="hidden" name="membership_id" value={membershipId} />
      <input type="hidden" name="idempotency_key" value={idempotencyKey} />
    </>
  );
}

function blockedReason(lastOwner: boolean, lastManager: boolean, canTargetRole: boolean): string {
  if (!canTargetRole) return "只有负责人可以管理负责人角色";
  if (lastOwner) return "不能撤销或降级最后一位负责人";
  if (lastManager) return "不能移除项目最后一个管理角色";
  return "当前状态不允许此操作";
}

function formatCreatedAt(value: string): string {
  return value ? value.slice(0, 16).replace("T", " ") : "时间未知";
}
