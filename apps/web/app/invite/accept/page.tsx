import { revalidatePath } from "next/cache";

type InviteAcceptSearchParams = Promise<{
  invitation_id?: string;
  invite_token?: string;
}>;

type AcceptedInvitation = {
  id?: string;
  project_id?: string;
  email?: string;
  role?: string;
  status?: string;
  member?: {
    user_id?: string;
    role?: string;
  };
};

type InviteAcceptApiPayload = {
  invitation?: AcceptedInvitation;
  audit_events?: Array<{
    event_type?: string;
    method_version?: string;
  }>;
  detail?: string;
};

type InviteAcceptResult =
  | {
      status: "idle";
    }
  | {
      status: "accepted";
      invitation: AcceptedInvitation;
      audit_events: Array<{
        event_type?: string;
        method_version?: string;
      }>;
    }
  | {
      status: "failed";
      detail: string;
    };

export const dynamic = "force-dynamic";

async function acceptProjectInvitation(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const invitationId = String(formData.get("invitation_id") || "").trim();
  const inviteToken = String(formData.get("invite_token") || "").trim();
  if (!invitationId || !inviteToken) {
    throw new Error("invitation_id and invite_token are required");
  }
  const response = await fetch(`${baseUrl}/v1/project-member-invitations/runtime/accept`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      invitation_id: invitationId,
      invite_token: inviteToken,
      accepted_by: String(formData.get("accepted_by") || "").trim() || undefined,
      reason: "Accept invitation from invite link"
    }),
    cache: "no-store"
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail || `/v1/project-member-invitations/runtime/accept returned ${response.status}`);
  }
  revalidatePath("/invite/accept");
}

async function acceptPreview(invitationId: string, inviteToken: string): Promise<InviteAcceptResult> {
  if (!invitationId || !inviteToken || process.env.GEO_WEB_INVITE_ACCEPT_AUTO_SUBMIT !== "1") {
    return { status: "idle" };
  }
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const response = await fetch(`${baseUrl}/v1/project-member-invitations/runtime/accept`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      invitation_id: invitationId,
      invite_token: inviteToken,
      reason: "Accept invitation from invite link"
    }),
    cache: "no-store"
  });
  const payload = (await response.json().catch(() => null)) as InviteAcceptApiPayload | null;
  if (!response.ok) {
    return { status: "failed", detail: payload?.detail || `accept endpoint returned ${response.status}` };
  }
  return {
    status: "accepted",
    invitation: payload?.invitation || {},
    audit_events: payload?.audit_events || []
  };
}

export default async function InviteAcceptPage({
  searchParams
}: {
  searchParams: InviteAcceptSearchParams;
}) {
  const params = await searchParams;
  const invitationId = String(params.invitation_id || "").trim();
  const inviteToken = String(params.invite_token || "").trim();
  const result = await acceptPreview(invitationId, inviteToken);

  return (
    <main className="inviteShell">
      <section className="invitePanel">
        <div className="panelHeader">
          <div>
            <h1>Project Invitation</h1>
            <span>project_member_invitation_accepted</span>
          </div>
        </div>
        {result.status === "accepted" ? (
          <div className="inviteResult">
            <strong>{result.invitation.email || result.invitation.member?.user_id || "Accepted"}</strong>
            <span>
              {result.invitation.status || "accepted"} · {result.invitation.role || result.invitation.member?.role || "member"}
            </span>
            <small>{result.audit_events.map((event) => event.event_type).filter(Boolean).join(" · ")}</small>
          </div>
        ) : result.status === "failed" ? (
          <div className="noticeMini">{result.detail}</div>
        ) : null}
        <form action={acceptProjectInvitation} className="inviteAcceptForm">
          <label>
            <span>Invitation ID</span>
            <input name="invitation_id" defaultValue={invitationId} />
          </label>
          <label>
            <span>Invite token</span>
            <input name="invite_token" defaultValue={inviteToken} />
          </label>
          <label>
            <span>Email</span>
            <input name="accepted_by" type="email" placeholder="viewer@example.com" />
          </label>
          <button type="submit">Accept invitation</button>
        </form>
      </section>
    </main>
  );
}
