import { logoutSession } from "@geo/auth/bff";

import { apiBase } from "../../../runtime";

export function POST(request: Request): Promise<Response> {
  return logoutSession(request, {
    apiBase: apiBase(),
    landingPath: "/",
    surface: "customer"
  });
}
