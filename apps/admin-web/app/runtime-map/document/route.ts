import { readFile } from "node:fs/promises";
import path from "node:path";

export const dynamic = "force-dynamic";

const runtimeMapRelativePath = "docs/architecture/GEO-runtime-flow-visualization.html";

type RuntimeMapFailureKind = "invalid" | "missing" | "read_failed";

class RuntimeMapDocumentError extends Error {
  constructor(readonly kind: RuntimeMapFailureKind, message: string, options?: ErrorOptions) {
    super(message, options);
    this.name = "RuntimeMapDocumentError";
  }
}

export async function GET(request: Request): Promise<Response> {
  try {
    const source = await readRuntimeMap();
    const customerWebBase = resolveCustomerWebBase(request);
    const document = source.replace(
      "<body>",
      `<body class="admin-embedded" data-customer-web-base="${escapeHtmlAttribute(customerWebBase)}">`
    );
    if (document === source) {
      throw new RuntimeMapDocumentError("invalid", "运行地图缺少可嵌入的 body 元素");
    }
    return new Response(document, {
      headers: {
        "Cache-Control": "no-store",
        "Content-Security-Policy": "default-src 'none'; img-src data:; script-src 'unsafe-inline'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'",
        "Content-Type": "text/html; charset=utf-8",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "SAMEORIGIN"
      }
    });
  } catch (error) {
    const kind = error instanceof RuntimeMapDocumentError ? error.kind : "read_failed";
    console.error(`[runtime-map:${kind}] failed to load visualization`, error);
    return new Response(
      `<!doctype html><html lang="zh-CN"><body><main><h1>运行地图暂不可用</h1><p>${failureMessage(kind)}</p></main></body></html>`,
      {
        status: 500,
        headers: {
          "Cache-Control": "no-store",
          "Content-Type": "text/html; charset=utf-8",
          "X-Content-Type-Options": "nosniff"
        }
      }
    );
  }
}

async function readRuntimeMap(): Promise<string> {
  const candidates = Array.from(new Set([
    path.resolve(process.cwd(), runtimeMapRelativePath),
    path.resolve(process.cwd(), "../..", runtimeMapRelativePath)
  ]));
  for (const candidate of candidates) {
    try {
      return await readFile(candidate, "utf8");
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    }
  }
  throw new RuntimeMapDocumentError("missing", `运行地图源文件不存在：${runtimeMapRelativePath}`);
}

function resolveCustomerWebBase(request: Request): string {
  const requestUrl = new URL(request.url);
  const configured = process.env.CUSTOMER_WEB_BASE_URL?.trim()
    || process.env.NEXT_PUBLIC_CUSTOMER_WEB_BASE_URL?.trim();
  let target: URL;
  try {
    target = configured ? new URL(configured) : new URL(requestUrl);
  } catch (error) {
    throw new RuntimeMapDocumentError("read_failed", "Customer Web 地址配置无效", { cause: error });
  }
  if (!configured) target.port = process.env.GEO_CUSTOMER_WEB_HOST_PORT?.trim() || "13000";
  if (isLoopback(target.hostname) && !isLoopback(requestUrl.hostname)) {
    target.protocol = requestUrl.protocol;
    target.hostname = requestUrl.hostname;
  }
  target.pathname = "";
  target.search = "";
  target.hash = "";
  return target.toString().replace(/\/$/, "");
}

function isLoopback(hostname: string): boolean {
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "::1";
}

function escapeHtmlAttribute(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function failureMessage(kind: RuntimeMapFailureKind): string {
  if (kind === "missing") {
    return "运行地图快照未随 Admin 部署。请重新构建 Admin 镜像，并确认 docs/architecture 下的快照已进入镜像。";
  }
  if (kind === "invalid") {
    return "运行地图快照格式无效，无法嵌入后台。请修复快照的 HTML body 后重新构建。";
  }
  return "Admin 无法读取运行地图快照或运行配置。请检查服务器日志中的 runtime-map:read_failed 错误、文件权限和 Customer Web 地址配置后重试。";
}
