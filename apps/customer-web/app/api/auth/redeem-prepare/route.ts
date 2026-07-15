import { prepareInvitation } from "@geo/auth/bff";

import { apiBase } from "../../../runtime";

export function POST(request: Request): Promise<Response> {
  return prepareInvitation(request, { apiBase: apiBase(), surface: "customer" });
}
