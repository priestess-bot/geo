import { CustomerApiClient } from "./customer";
import { InternalApiClient } from "./internal";
import { AuthApiClient } from "./auth";
import { GeoAdminApiClient } from "./geo";

const customer = new CustomerApiClient("https://customer-api.example.test");
const internal = new InternalApiClient("https://internal-api.example.test");
const auth = new AuthApiClient("https://customer-api.example.test");
const geoAdmin = new GeoAdminApiClient("https://internal-api.example.test");

customer.currentIdentity();
customer.listProjects();
customer.listGeoCampaigns("project-id");
customer.getGeoCampaignReadModel("project-id", "campaign-id");
customer.getGeoSummary("project-id", "campaign-id");
customer.listGeoMetrics("project-id", "campaign-id");
customer.listMeasurementWindows("project-id", "campaign-id");
customer.listVerifiedUrls("project-id", "campaign-id");
customer.listApprovedReports("project-id", "campaign-id");
customer.listWorkflowCApprovedReports("project-id", "campaign-id");
internal.listEngineeringWorkItems();
geoAdmin.listPromptSimulations("project-id");
geoAdmin.listPromptSimulations("project-id", "campaign-id");
geoAdmin.getPromptSimulation("project-id", "simulation-id");
geoAdmin.getPromptSimulation("project-id", "campaign-id", "simulation-id");
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

// Legacy Customer runtime endpoints are not addressable through named operations.
// @ts-expect-error the stable customer client has no generic call escape hatch
customer.call("/v1/geo/customer-summary");

// Neither client exposes a generic request(path) escape hatch.
// @ts-expect-error only named or typed customer operations are public
customer.request("/v1/projects");
// @ts-expect-error only named internal operations are public
internal.request("/v1/engineering/work-items");
