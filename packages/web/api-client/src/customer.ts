import type { CustomerProjectSummary } from "@geo/types/customer";
import { requestJson } from "./transport";

export class CustomerApiClient {
  constructor(private readonly baseUrl: string) {}

  listProjects(): Promise<{ items: CustomerProjectSummary[] }> {
    return requestJson(this.baseUrl, "/v1/projects");
  }
}
