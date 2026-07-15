import { CustomerApiClient } from "./customer";
import { InternalApiClient } from "./internal";

const customer = new CustomerApiClient("https://customer-api.example.test");
const internal = new InternalApiClient("https://internal-api.example.test");

customer.call("/v1/auth/me");
internal.listEngineeringWorkItems();

// The customer client cannot address an internal engineering resource.
// @ts-expect-error internal paths are intentionally absent from CustomerApiPath
customer.call("/v1/engineering/work-items");

// Neither client exposes a generic request(path) escape hatch.
// @ts-expect-error only named or typed customer operations are public
customer.request("/v1/projects");
// @ts-expect-error only named internal operations are public
internal.request("/v1/engineering/work-items");
