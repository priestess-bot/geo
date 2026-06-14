import { revalidatePath } from "next/cache";

type EmailPreferenceSearchParams = Promise<{
  token?: string;
}>;

type EmailPreferenceStatusPayload = {
  preference?: {
    project_id?: string;
    delivery_id?: string;
    notification_id?: string;
    subscription_id?: string;
    recipient_hash?: string;
    channel?: string;
    status?: string;
    suppressed?: boolean;
    subscription_status?: string;
    severity_threshold?: string;
    email_suppressed_recipient_hash_count?: number;
    email_unsubscribe_token_hash_seen?: boolean;
    email_resubscribe_token_hash_seen?: boolean;
    method_version?: string;
  };
  delivery?: {
    id?: string;
    channel?: string;
    status?: string;
    response_status?: number | null;
    response_body_hash?: string | null;
    updated_by?: string;
  };
  notification?: {
    id?: string;
    notification_type?: string;
    severity?: string;
    title?: string;
    target_type?: string;
    target_id?: string;
  } | null;
  subscription?: {
    id?: string;
    channel?: string;
    status?: string;
    severity_threshold?: string;
    metadata?: {
      email_suppressed_recipient_hash_count?: number;
      email_unsubscribe_token_hash_count?: number;
      email_resubscribe_token_hash_count?: number;
      email_unsubscribe_source?: string | null;
      email_resubscribe_source?: string | null;
    };
  };
  audit_events?: Array<{
    event_type?: string;
    method_version?: string;
    created_at?: string;
    reason?: string;
  }>;
  detail?: string;
};

type EmailPreferenceStatusResult =
  | {
      status: "missing_token";
    }
  | {
      status: "loaded";
      payload: EmailPreferenceStatusPayload;
    }
  | {
      status: "failed";
      detail: string;
    };

export const dynamic = "force-dynamic";

function apiBaseUrl(): string {
  return process.env.API_INTERNAL_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
}

async function fetchEmailPreferenceStatus(token: string): Promise<EmailPreferenceStatusResult> {
  if (!token) {
    return { status: "missing_token" };
  }
  const params = new URLSearchParams({ token });
  const response = await fetch(`${apiBaseUrl()}/v1/runtime-notification-email-preferences/status?${params.toString()}`, {
    cache: "no-store"
  });
  const payload = (await response.json().catch(() => null)) as EmailPreferenceStatusPayload | null;
  if (!response.ok) {
    return {
      status: "failed",
      detail: payload?.detail || `/v1/runtime-notification-email-preferences/status returned ${response.status}`
    };
  }
  return { status: "loaded", payload: payload || {} };
}

async function updateEmailPreference(formData: FormData) {
  "use server";
  const token = String(formData.get("token") || "").trim();
  const action = String(formData.get("action") || "").trim();
  if (!token || !action) {
    throw new Error("token and action are required");
  }
  const endpoint =
    action === "resubscribe"
      ? "/v1/runtime-notification-email-preferences/resubscribe"
      : "/v1/runtime-notification-email-preferences/unsubscribe";
  const response = await fetch(`${apiBaseUrl()}${endpoint}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      token,
      reason: `runtime notification email preference ${action} from preferences page`
    }),
    cache: "no-store"
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail || `${endpoint} returned ${response.status}`);
  }
  revalidatePath("/notifications/preferences");
}

function shortHash(value: string | undefined): string {
  return value ? `${value.slice(0, 12)}...${value.slice(-6)}` : "none";
}

export default async function EmailNotificationPreferencesPage({
  searchParams
}: {
  searchParams: EmailPreferenceSearchParams;
}) {
  const params = await searchParams;
  const token = String(params.token || "").trim();
  const result = await fetchEmailPreferenceStatus(token);
  const payload = result.status === "loaded" ? result.payload : {};
  const preference = payload.preference || {};
  const isSuppressed = Boolean(preference.suppressed);
  const statusLabel = preference.status || (isSuppressed ? "unsubscribed" : "subscribed");

  return (
    <main className="preferenceShell">
      <section className="preferencePanel">
        <header className="panelHeader">
          <div>
            <h1>Email Preferences</h1>
            <span>runtime_notification_email_preference_status_v1</span>
          </div>
        </header>

        {result.status === "missing_token" ? (
          <div className="noticeMini">token is required</div>
        ) : result.status === "failed" ? (
          <div className="noticeMini">{result.detail}</div>
        ) : (
          <>
            <div className={`preferenceStatus ${isSuppressed ? "isSuppressed" : "isSubscribed"}`}>
              <strong>{statusLabel}</strong>
              <span>{payload.notification?.title || payload.notification?.notification_type || "runtime notification"}</span>
            </div>

            <dl className="facts preferenceFacts">
              <Fact label="Notification" value={payload.notification?.id || preference.notification_id || "none"} />
              <Fact label="Delivery" value={payload.delivery?.id || preference.delivery_id || "none"} />
              <Fact label="Subscription" value={payload.subscription?.id || preference.subscription_id || "none"} />
              <Fact label="Recipient hash" value={shortHash(preference.recipient_hash)} />
              <Fact label="Channel" value={payload.subscription?.channel || preference.channel || "email"} />
              <Fact label="Subscription status" value={preference.subscription_status || payload.subscription?.status || "unknown"} />
              <Fact
                label="Suppressed hashes"
                value={
                  preference.email_suppressed_recipient_hash_count ??
                  payload.subscription?.metadata?.email_suppressed_recipient_hash_count ??
                  0
                }
              />
              <Fact label="Method" value={preference.method_version || "runtime_notification_email_preference_status_v1"} />
            </dl>

            <form action={updateEmailPreference} className="preferenceActionForm">
              <input type="hidden" name="token" value={token} />
              {isSuppressed ? (
                <button name="action" value="resubscribe" type="submit">
                  Resubscribe
                </button>
              ) : (
                <button name="action" value="unsubscribe" type="submit">
                  Unsubscribe
                </button>
              )}
            </form>

            {payload.audit_events?.length ? (
              <ul className="preferenceAuditList">
                {payload.audit_events.slice(0, 5).map((event, index) => (
                  <li key={`${event.event_type || "event"}-${index}`}>
                    <strong>{event.event_type || "audit_event"}</strong>
                    <span>{event.method_version || "method_unknown"}</span>
                    <small>{event.created_at || event.reason || "recorded"}</small>
                  </li>
                ))}
              </ul>
            ) : null}
          </>
        )}
      </section>
    </main>
  );
}

function Fact({ label, value }: { label: string; value: string | number }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </>
  );
}
