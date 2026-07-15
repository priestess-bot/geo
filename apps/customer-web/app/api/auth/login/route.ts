import { redeemInvitation } from "@geo/auth/bff";

import { apiBase } from "../../../runtime";

export function POST(request: Request): Promise<Response> {
  return redeemInvitation(request, {
    apiBase: apiBase(),
    landingPath: "/",
    surface: "customer"
  });
}
