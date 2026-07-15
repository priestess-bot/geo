import type { InvitationRequest } from "@geo/types/auth";

export type AuthApiFetch = (input: string | URL, init?: RequestInit) => Promise<Response>;

export class AuthApiClient {
  private readonly baseUrl: string;
  private readonly fetcher: AuthApiFetch;

  constructor(
    baseUrl: string,
    fetcher: AuthApiFetch = fetch
  ) {
    this.baseUrl = baseUrl;
    this.fetcher = fetcher;
  }

  preflight(payload: InvitationRequest): Promise<Response> {
    return this.post("/v1/auth/invitations/preflight", payload);
  }

  redeem(payload: InvitationRequest, idempotencyKey: string): Promise<Response> {
    return this.post("/v1/auth/invitations/redeem", payload, {
      "Idempotency-Key": idempotencyKey
    });
  }

  logout(cookieHeader: string, csrfToken: string): Promise<Response> {
    return this.fetcher(new URL("/v1/auth/logout", this.baseUrl), {
      method: "POST",
      headers: {
        Cookie: cookieHeader,
        "X-GEO-CSRF-Token": csrfToken
      },
      cache: "no-store",
      redirect: "manual"
    });
  }

  private post(
    path: string,
    payload: InvitationRequest,
    extraHeaders: Record<string, string> = {}
  ): Promise<Response> {
    return this.fetcher(new URL(path, this.baseUrl), {
      method: "POST",
      headers: { "Content-Type": "application/json", ...extraHeaders },
      body: JSON.stringify(payload),
      cache: "no-store",
      redirect: "manual"
    });
  }
}
