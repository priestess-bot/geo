import { GeoAdminApiClient } from "@geo/api-client/geo";
import { actorHeaders, apiBase } from "../../../runtime";

export async function geoClient(): Promise<GeoAdminApiClient> {
  return new GeoAdminApiClient(apiBase(), { headers: await actorHeaders(), cache: "no-store" });
}
