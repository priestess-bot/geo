"use client";

import { useActionState } from "react";

import { addProjectMemberAction } from "./memberActions";
import { MemberActionFeedback } from "./MemberActionFeedback";
import {
  initialMemberActionState,
  managedMemberRoles,
  type ManagedMemberRole
} from "./memberTypes";
import styles from "./MemberGovernance.module.css";

const roleLabels: Record<ManagedMemberRole, string> = {
  owner: "负责人",
  admin: "管理员",
  analyst: "分析师 / 审核员"
};

export function AddMemberForm({
  actorRole,
  idempotencyKey,
  projectId
}: {
  actorRole: ManagedMemberRole;
  idempotencyKey: string;
  projectId: string;
}) {
  const [state, action, pending] = useActionState(
    addProjectMemberAction,
    initialMemberActionState
  );
  return (
    <form className={styles.addForm} action={action}>
      <input type="hidden" name="project_id" value={projectId} />
      <input type="hidden" name="idempotency_key" value={idempotencyKey} />
      <div className={styles.formHeading}>
        <div>
          <p>添加内部成员</p>
          <strong>OIDC 身份</strong>
        </div>
        <button type="submit" disabled={pending}>
          {pending ? "添加中..." : "添加成员"}
        </button>
      </div>
      <div className={styles.formGrid}>
        <label>
          <span>签发方</span>
          <input
            name="issuer"
            type="url"
            inputMode="url"
            placeholder="https://idp.example.com/"
            autoComplete="off"
            required
          />
        </label>
        <label>
          <span>主体标识</span>
          <input name="subject" autoComplete="off" required />
        </label>
        <label>
          <span>邮箱</span>
          <input name="email" type="email" autoComplete="email" required />
        </label>
        <label>
          <span>显示名称</span>
          <input name="display_name" autoComplete="name" required />
        </label>
        <label>
          <span>项目角色</span>
          <select name="role" defaultValue="analyst">
            {managedMemberRoles.map((role) => (
              <option key={role} value={role} disabled={role === "owner" && actorRole !== "owner"}>
                {roleLabels[role]}
              </option>
            ))}
          </select>
        </label>
      </div>
      <MemberActionFeedback state={state} />
    </form>
  );
}
