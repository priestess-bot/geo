import { CustomerApiClient } from "./customer";
import { InternalApiClient } from "./internal";
import { AuthApiClient } from "./auth";

const customer = new CustomerApiClient("https://customer-api.example.test");
const internal = new InternalApiClient("https://internal-api.example.test");
const auth = new AuthApiClient("https://customer-api.example.test");

customer.call("/v1/auth/me");
internal.listEngineeringWorkItems();
auth.preflight({
  invitation_id: "invitation-id",
  invite_token: "one-time-token",
  requested_surface: "customer"
});
auth.redeem({
  invitation_id: "invitation-id",
  invite_token: "one-time-token",
  requested_surface: "customer"
}, "idempotency-key");

// The customer client cannot address an internal engineering resource.
// @ts-expect-error internal paths are intentionally absent from CustomerApiPath
customer.call("/v1/engineering/work-items");

// Neither client exposes a generic request(path) escape hatch.
// @ts-expect-error only named or typed customer operations are public
customer.request("/v1/projects");
// @ts-expect-error only named internal operations are public
internal.request("/v1/engineering/work-items");
