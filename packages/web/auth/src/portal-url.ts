export function resolveCounterpartPortalUrl({
  configuredValue,
  deploymentEnvironment,
  developmentFallback,
  environmentName,
  nodeEnv,
  publicDevelopmentValue
}: {
  configuredValue?: string;
  deploymentEnvironment?: string;
  developmentFallback: string;
  environmentName: "ADMIN_WEB_BASE_URL" | "CUSTOMER_WEB_BASE_URL";
  nodeEnv?: string;
  publicDevelopmentValue?: string;
}): string {
  const deployment = deploymentEnvironment?.trim().toLowerCase();
  const localDevelopment = deployment
    ? deployment === "development"
    : nodeEnv !== "production";
  const configured = configuredValue?.trim() || "";
  if (!localDevelopment && !configured) {
    throw new Error(`${environmentName} is required in production`);
  }
  const candidate = configured
    || (localDevelopment ? publicDevelopmentValue?.trim() : "")
    || (localDevelopment ? developmentFallback : "");
  let url: URL;
  try {
    url = new URL(candidate);
  } catch {
    throw new Error(`${environmentName} must be an absolute URL`);
  }
  if (url.username || url.password) {
    throw new Error(`${environmentName} must not contain userinfo`);
  }
  if (url.protocol === "https:") {
    return url.toString();
  }
  if (url.protocol === "http:" && localDevelopment && isLoopbackHost(url.hostname)) {
    return url.toString();
  }
  throw new Error(`${environmentName} must use HTTPS outside local development`);
}

function isLoopbackHost(hostname: string): boolean {
  const normalized = hostname.toLowerCase().replace(/^\[|\]$/g, "");
  return normalized === "localhost" || normalized === "127.0.0.1" || normalized === "::1";
}
