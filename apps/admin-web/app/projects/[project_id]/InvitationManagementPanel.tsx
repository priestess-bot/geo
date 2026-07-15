import { randomUUID } from "node:crypto";

import {
  InvitationCreateForm,
  InvitationRevokeForm
} from "./InvitationForms";
import type { InvitationLoadResult } from "./invitationTypes";
import { ResourceProblem } from "./ResourceProblem";
import styles from "./Catalog.module.css";

export function InvitationManagementPanel({
  data,
  projectId
}: {
  data: InvitationLoadResult;
  projectId: string;
}) {
  const pending = data.page.items.filter((invitation) => invitation.status === "pending");
  return (
    <section className={styles.section} id="invitations">
      <header className={styles.sectionHeader}>
        <div><p>Customer access</p><h2>客户邀请</h2></div>
        <span className={styles.badge}>{pending.length} 条当前页待兑换 / {data.page.total} 条全部</span>
      </header>
      {!data.problem ? (
        <InvitationCreateForm
          idempotencyKey={`admin-invitation-${randomUUID()}`}
          projectId={projectId}
        />
      ) : null}
      {data.problem ? <ResourceProblem label="客户邀请" problem={data.problem} /> : null}
      {!data.problem && !data.page.items.length ? <div className={styles.empty}>暂无客户邀请。</div> : null}
      {data.page.items.length ? (
        <div className={styles.list}>
          {data.page.items.map((invitation) => (
            <article className={styles.row} key={invitation.id}>
              <div className={styles.rowMain}><strong>{invitation.email}</strong><small>{invitation.id}</small></div>
              <div className={styles.rowMeta}><span>{invitation.role}</span><span>{statusLabel(invitation.status)}</span><small>到期：{formatDate(invitation.expires_at)}</small></div>
              <div className={styles.rowMeta}>
                <small>Token hint：{invitation.token_hint}</small>
                {invitation.status === "pending" ? (
                  <InvitationRevokeForm invitationId={invitation.id} projectId={projectId} />
                ) : null}
              </div>
            </article>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function statusLabel(status: string): string {
  if (status === "pending") return "待兑换";
  if (status === "redeemed") return "已兑换";
  if (status === "revoked") return "已撤销";
  return "已过期";
}

function formatDate(value: string): string {
  return value.slice(0, 16).replace("T", " ");
}
