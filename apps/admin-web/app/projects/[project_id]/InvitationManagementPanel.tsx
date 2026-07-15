import { randomUUID } from "node:crypto";

import { InvitationForm, InvitationList } from "./ProjectActions";

type InvitationRecord = Record<string, unknown>;

export function InvitationManagementPanel({
  defaultEmail,
  invitations,
  projectId
}: {
  defaultEmail?: string;
  invitations: InvitationRecord[];
  projectId: string;
}) {
  const pending = invitations.filter((record) => {
    const invitation = record.invitation;
    return invitation !== null
      && typeof invitation === "object"
      && !Array.isArray(invitation)
      && (invitation as Record<string, unknown>).status === "pending";
  });
  return (
    <div className="detailPanel nestedPanel">
      <div className="sectionTitle">
        <div>
          <p className="eyebrow">客户邀请</p>
          <h3>创建和跟踪客户入口</h3>
        </div>
      </div>
      <InvitationForm
        projectId={projectId}
        defaultEmail={defaultEmail}
        idempotencyKey={`admin-invitation-${randomUUID()}`}
        pendingInvitations={pending}
      />
      <InvitationList invitations={invitations} projectId={projectId} />
    </div>
  );
}
