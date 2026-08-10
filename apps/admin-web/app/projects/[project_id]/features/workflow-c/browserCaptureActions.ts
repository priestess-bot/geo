"use server";

import { revalidatePath } from "next/cache";

import { runtimeRequest } from "../../../../runtime";
import {
  commandFailure,
  field,
  invalid,
  UUID_PATTERN,
  verifyWorkflowCActor
} from "./workflowCActionSupport";
import type { WorkflowCActionState } from "./workflowCTypes";

const OPERATORS = ["owner", "admin", "analyst"] as const;
const SURFACES = new Set([
  "google_ai_overviews",
  "google_ai_mode",
  "bing_copilot"
]);

export async function bootstrapBrowserCaptureAction(
  _previous: WorkflowCActionState,
  formData: FormData
): Promise<WorkflowCActionState> {
  const command = baseCommand(formData);
  if (!command.ok) return command.state;
  const access = await verifyWorkflowCActor(command.projectId, OPERATORS);
  if (!access.ok) return access.state;
  const response = await runtimeRequest<unknown>(
    `/v1/projects/${encodeURIComponent(command.projectId)}/browser-capture/bootstrap`,
    {
      method: "POST",
      body: {
        surfaces: ["google_ai_overviews", "google_ai_mode", "bing_copilot"],
        terms_acknowledged: true
      }
    }
  );
  if (!response.ok) return commandFailure(response, "消费者界面采集器安装失败。");
  refresh(command.projectId);
  return { kind: "success", message: "三个消费者界面采集器和匿名澳洲浏览器配置已启用。" };
}

export async function configureLokiProxyPoolAction(
  _previous: WorkflowCActionState,
  formData: FormData
): Promise<WorkflowCActionState> {
  const command = baseCommand(formData);
  if (!command.ok) return command.state;
  const endpointHost = field(formData, "endpoint_host");
  const endpointPort = Number(field(formData, "endpoint_port"));
  const usernameTemplate = field(formData, "username_template");
  const password = field(formData, "password");
  const protocol = field(formData, "protocol");
  const poolProduct = field(formData, "pool_product");
  const sessionTtlSeconds = Number(field(formData, "session_ttl_seconds"));
  const maxConcurrency = Number(field(formData, "max_concurrency"));
  if (!endpointHost || endpointHost.length > 253
    || !Number.isSafeInteger(endpointPort) || endpointPort < 1 || endpointPort > 65535) {
    return invalid("请填写有效的代理主机和端口。");
  }
  if (!usernameTemplate.includes("{session_id}")) {
    return invalid("粘性用户名模板必须包含 {session_id}。");
  }
  if (!password || password.length > 4000) return invalid("请填写有效的代理密码。");
  if (!new Set(["http", "https"]).has(protocol)
    || !new Set(["rotating_residential", "mobile"]).has(poolProduct)) {
    return invalid("请选择 LokiProxy 支持的浏览器代理协议和产品类型。");
  }
  if (!Number.isSafeInteger(sessionTtlSeconds)
    || sessionTtlSeconds < 300 || sessionTtlSeconds > 10_800) {
    return invalid("粘性会话时长必须在 5 至 180 分钟之间。");
  }
  if (!Number.isSafeInteger(maxConcurrency)
    || maxConcurrency < 1 || maxConcurrency > 100) {
    return invalid("并发上限必须在 1 至 100 之间。");
  }
  const access = await verifyWorkflowCActor(command.projectId, OPERATORS);
  if (!access.ok) return access.state;
  const response = await runtimeRequest<unknown>(
    `/v1/projects/${encodeURIComponent(command.projectId)}/browser-capture/lokiproxy-pool`,
    {
      method: "POST",
      idempotencyKey: command.idempotencyKey,
      body: {
        name: "LokiProxy 澳洲消费者搜索 IP 池",
        protocol,
        endpoint_host: endpointHost,
        endpoint_port: endpointPort,
        username_template: usernameTemplate,
        password,
        pool_product: poolProduct,
        expected_region: optional(formData, "expected_region"),
        session_ttl_seconds: sessionTtlSeconds,
        max_concurrency: maxConcurrency
      }
    }
  );
  if (!response.ok) return commandFailure(
    response,
    "LokiProxy IP 池保存失败。请核对 Host、Port、用户名模板和套餐类型后重试。"
  );
  refresh(command.projectId);
  return { kind: "success", message: "LokiProxy 凭据已加密保存；下一步测试真实澳洲出口。" };
}

export async function testAustralianEgressAction(
  _previous: WorkflowCActionState,
  formData: FormData
): Promise<WorkflowCActionState> {
  const command = baseCommand(formData);
  if (!command.ok) return command.state;
  const endpointId = field(formData, "endpoint_id");
  if (!UUID_PATTERN.test(endpointId)) return invalid("澳洲代理配置无效。");
  const access = await verifyWorkflowCActor(command.projectId, OPERATORS);
  if (!access.ok) return access.state;
  const response = await runtimeRequest<unknown>(
    `/v1/projects/${encodeURIComponent(command.projectId)}/browser-capture/`
      + `egress-endpoints/${encodeURIComponent(endpointId)}/tests`,
    { method: "POST", idempotencyKey: command.idempotencyKey }
  );
  if (!response.ok) return commandFailure(response, "澳洲出口测试未能入队。");
  refresh(command.projectId);
  return { kind: "success", message: "澳洲出口测试已入队，完成后页面会显示真实地域结果。" };
}

export async function configureBrowserSessionAction(
  _previous: WorkflowCActionState,
  formData: FormData
): Promise<WorkflowCActionState> {
  const command = baseCommand(formData);
  if (!command.ok) return command.state;
  const storageStateJson = field(formData, "storage_state_json");
  if (!storageStateJson || new TextEncoder().encode(storageStateJson).length > 2_000_000) {
    return invalid("请粘贴不超过 2 MB 的 Playwright storage_state JSON。");
  }
  try {
    const value: unknown = JSON.parse(storageStateJson);
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error();
  } catch {
    return invalid("登录会话不是有效的 JSON 对象。");
  }
  const access = await verifyWorkflowCActor(command.projectId, OPERATORS);
  if (!access.ok) return access.state;
  const response = await runtimeRequest<unknown>(
    `/v1/projects/${encodeURIComponent(command.projectId)}/browser-capture/`
      + "session-profile-setup",
    {
      method: "POST",
      idempotencyKey: command.idempotencyKey,
      body: { storage_state_json: storageStateJson }
    }
  );
  if (!response.ok) return commandFailure(response, "登录会话导入失败。");
  refresh(command.projectId);
  return { kind: "success", message: "登录会话已加密保存，并启用为当前受管账号浏览器配置。" };
}

export async function registerBrowserRuntimeOptionAction(
  _previous: WorkflowCActionState,
  formData: FormData
): Promise<WorkflowCActionState> {
  const command = baseCommand(formData);
  if (!command.ok) return command.state;
  const ids = runtimeIds(formData);
  if (!ids) return invalid("消费者界面、代理或浏览器配置无效。");
  const access = await verifyWorkflowCActor(command.projectId, OPERATORS);
  if (!access.ok) return access.state;
  const response = await runtimeRequest<unknown>(
    `/v1/projects/${encodeURIComponent(command.projectId)}/browser-capture/sampling-options`,
    { method: "POST", body: ids }
  );
  if (!response.ok) return commandFailure(response, "自动采样授权选项注册失败。");
  refresh(command.projectId);
  return { kind: "success", message: "自动采样授权选项已注册；现在可以创建对应准入策略。" };
}

export async function registerBrowserSamplingInputAction(
  _previous: WorkflowCActionState,
  formData: FormData
): Promise<WorkflowCActionState> {
  const command = baseCommand(formData);
  if (!command.ok) return command.state;
  const ids = runtimeIds(formData);
  const questionSetId = field(formData, "question_set_id");
  const admissionPolicyId = field(formData, "admission_policy_id");
  const surface = field(formData, "surface");
  if (!ids || !UUID_PATTERN.test(questionSetId) || !UUID_PATTERN.test(admissionPolicyId)
    || !SURFACES.has(surface)) {
    return invalid("请选择已冻结问题集和匹配的自动采样策略。");
  }
  const access = await verifyWorkflowCActor(command.projectId, OPERATORS);
  if (!access.ok) return access.state;
  const optionKey = `browser-${surface}-${questionSetId.slice(0, 8)}-${ids.surface_release_id.slice(0, 8)}`;
  const response = await runtimeRequest<unknown>(
    `/v1/projects/${encodeURIComponent(command.projectId)}/browser-capture/`
      + "sampling-suite-inputs",
    {
      method: "POST",
      body: {
        ...ids,
        question_set_id: questionSetId,
        admission_policy_id: admissionPolicyId,
        option_key: optionKey,
        display_name: `${surfaceLabel(surface)} · 澳洲消费者界面`
      }
    }
  );
  if (!response.ok) return commandFailure(response, "消费者界面采样输入绑定失败。");
  refresh(command.projectId);
  return { kind: "success", message: "问题集已绑定；可在下方创建采样套件并启动运行。" };
}

function runtimeIds(formData: FormData) {
  const value = {
    surface_release_id: field(formData, "surface_release_id"),
    egress_endpoint_id: field(formData, "egress_endpoint_id"),
    profile_version_id: field(formData, "profile_version_id")
  };
  return Object.values(value).every((item) => UUID_PATTERN.test(item)) ? value : null;
}

function baseCommand(formData: FormData):
  | { ok: true; projectId: string; idempotencyKey: string }
  | { ok: false; state: WorkflowCActionState } {
  const projectId = field(formData, "project_id");
  const idempotencyKey = field(formData, "idempotency_key");
  if (!UUID_PATTERN.test(projectId)) return { ok: false, state: invalid("项目 ID 无效。") };
  if (idempotencyKey.length < 16 || idempotencyKey.length > 200) {
    return { ok: false, state: invalid("操作标识无效，请刷新页面重试。") };
  }
  return { ok: true, projectId, idempotencyKey };
}

function optional(formData: FormData, name: string): string | null {
  return String(formData.get(name) || "").trim() || null;
}

function refresh(projectId: string) {
  revalidatePath(`/projects/${projectId}`);
}

function surfaceLabel(value: string): string {
  return ({
    google_ai_overviews: "Google AI Overviews",
    google_ai_mode: "Google AI Mode",
    bing_copilot: "Bing Copilot"
  } as Record<string, string>)[value] || value;
}
