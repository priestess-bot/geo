"use server";

import { revalidatePath } from "next/cache";
import type { FormResult } from "../../geo/features/geo/ActionForm";
import { lines, parseJsonObject, runtimeRequest } from "../../../../runtime";

export async function externalOperation(
  _state: FormResult, form: FormData
): Promise<FormResult> {
  const projectId = field(form, "project_id");
  const command = field(form, "command");
  const base = `/v1/projects/${encodeURIComponent(projectId)}`;
  let request: { path: string; method: string; body?: unknown; idempotencyKey?: string };
  try {
    request = buildRequest(base, command, form);
  } catch (error) {
    return { error: error instanceof Error ? error.message : "输入无效。", status: 422 };
  }
  const result = await runtimeRequest<Record<string, unknown>>(request.path, {
    method: request.method,
    ...(request.idempotencyKey ? { idempotencyKey: request.idempotencyKey } : {}),
    ...(request.body === undefined ? {} : { body: request.body })
  });
  if (!result.ok) return {
    error: result.error, status: result.status, code: result.problem.type,
    correlationId: result.problem.correlation_id,
    retryable: result.status === undefined || result.status >= 500
  };
  revalidatePath(`/projects/${projectId}`);
  const oneTime = typeof result.data.write_key === "string"
    ? ` 写入密钥（仅显示一次）：${result.data.write_key}` : "";
  return { ok: `${successLabel(command)}${oneTime}` };
}

function buildRequest(base: string, command: string, form: FormData) {
  if (command === "install_definition") return {
    path: `${base}/connectors/definitions`, method: "POST", body: { kind: field(form, "kind") }
  };
  if (command === "approve_definition") return {
    path: `${base}/connectors/definitions/${id(form, "definition_id")}/approve`, method: "POST"
  };
  if (command === "create_connection") return {
    path: `${base}/connectors/connections`, method: "POST", body: {
      definition_id: id(form, "definition_id"), name: field(form, "name"),
      secret_reference_id: id(form, "secret_reference_id"),
      secret_purpose: field(form, "secret_purpose"),
      secret_version: integer(form, "secret_version")
    }
  };
  if (command === "set_connection_status") return {
    path: `${base}/connectors/connections/${id(form, "connection_id")}/status`,
    method: "POST", body: {
      status: field(form, "status"), expected_version: integer(form, "expected_version")
    }
  };
  if (command === "rotate_connection_secret") return {
    path: `${base}/connectors/connections/${id(form, "connection_id")}/rotate-secret`,
    method: "POST", body: {
      secret_version: integer(form, "secret_version"),
      expected_version: integer(form, "expected_version")
    }
  };
  if (command === "test_connection") {
    const connectionId = id(form, "connection_id");
    const expectedVersion = integer(form, "expected_version");
    return {
      path: `${base}/connectors/connections/${connectionId}/tests`, method: "POST",
      idempotencyKey: `connector-test:${connectionId}:v${expectedVersion}:${Date.now()}`,
      body: { expected_version: expectedVersion }
    };
  }
  if (command === "create_scope") return {
    path: `${base}/connectors/scopes`, method: "POST", body: {
      connection_id: id(form, "connection_id"), source_locator: field(form, "source_locator"),
      streams: lines(form.get("streams")), locale: "en-AU",
      report_spec: json(form, "report_spec"), date_policy: json(form, "date_policy")
    }
  };
  if (command === "start_sync") return {
    path: `${base}/connectors/scopes/${id(form, "scope_id")}/syncs`, method: "POST", body: {
      mode: field(form, "mode"), window_start: optional(form, "window_start"),
      window_end: optional(form, "window_end")
    }
  };
  if (command === "cancel_sync") return {
    path: `${base}/connectors/syncs/${id(form, "run_id")}/cancel`, method: "POST",
    body: { expected_version: integer(form, "expected_version") }
  };
  if (command === "create_policy") return {
    path: `${base}/attribution/policies`, method: "POST", body: {
      last_click_days: integer(form, "last_click_days"),
      assisted_days: integer(form, "assisted_days"), eligible_touch_types: ["page_view", "click"]
    }
  };
  if (command === "create_collector") return {
    path: `${base}/attribution/collectors`, method: "POST", body: {
      name: field(form, "name"), allowed_origins: lines(form.get("allowed_origins")),
      event_schema_version: "geo-attribution-event-v1", sdk_release: "geo-browser-sdk-v1"
    }
  };
  if (command === "create_snapshot") return {
    path: `${base}/attribution/snapshots`, method: "POST", body: {
      cutoff_at: field(form, "cutoff_at"), policy_id: optional(form, "policy_id")
    }
  };
  if (command === "approve_surface") return {
    path: `${base}/browser-capture/surface-releases/${id(form, "release_id")}/approve`,
    method: "POST"
  };
  if (command === "retire_surface") return {
    path: `${base}/browser-capture/surface-releases/${id(form, "release_id")}/retire`,
    method: "POST"
  };
  if (command === "create_surface") return {
    path: `${base}/browser-capture/surface-releases`, method: "POST", body: {
      platform: field(form, "platform"), surface: field(form, "surface"),
      release_version: field(form, "release_version"),
      entry_url_template: field(form, "entry_url_template"),
      allowed_hosts: lines(form.get("allowed_hosts")), selectors: json(form, "selectors"),
      block_detectors: json(form, "block_detectors"),
      parser_release: field(form, "parser_release"),
      browser_release: field(form, "browser_release"),
      authorization_track: field(form, "authorization_track"),
      authorization_status: field(form, "authorization_status"),
      authorization_reference: optional(form, "authorization_reference"),
      authorization_valid_until: optional(form, "authorization_valid_until"),
      terms_version: field(form, "terms_version")
    }
  };
  if (command === "set_egress_status") return {
    path: `${base}/browser-capture/egress-endpoints/${id(form, "endpoint_id")}/status`,
    method: "POST", body: { status: field(form, "status") }
  };
  if (command === "test_egress") {
    const endpointId = id(form, "endpoint_id");
    return {
      path: `${base}/browser-capture/egress-endpoints/${endpointId}/tests`,
      method: "POST", idempotencyKey: `browser-egress-test:${endpointId}:${Date.now()}`
    };
  }
  if (command === "approve_profile") return {
    path: `${base}/browser-capture/profiles/${id(form, "profile_id")}/approve`, method: "POST"
  };
  if (command === "create_profile") return {
    path: `${base}/browser-capture/profiles`, method: "POST", body: {
      version: field(form, "version"), browser_release: field(form, "browser_release"),
      device_class: field(form, "device_class"), viewport: json(form, "viewport"),
      timezone: "Australia/Sydney", location_permission: false, safe_search: "moderate",
      account_cohort: "clean_anonymous"
    }
  };
  if (command === "register_browser_sampling_input") return {
    path: `${base}/browser-capture/sampling-suite-inputs`, method: "POST", body: {
      surface_release_id: id(form, "surface_release_id"),
      egress_endpoint_id: id(form, "egress_endpoint_id"),
      profile_version_id: id(form, "profile_version_id"),
      question_set_id: id(form, "question_set_id"),
      admission_policy_id: id(form, "admission_policy_id"),
      option_key: field(form, "option_key"), display_name: field(form, "display_name")
    }
  };
  if (command === "register_browser_runtime_option") return {
    path: `${base}/browser-capture/sampling-options`, method: "POST", body: {
      surface_release_id: id(form, "surface_release_id"),
      egress_endpoint_id: id(form, "egress_endpoint_id"),
      profile_version_id: id(form, "profile_version_id")
    }
  };
  if (command === "enqueue_browser_capture") {
    const taskId = id(form, "task_id");
    const taskVersion = integer(form, "expected_task_version");
    return {
      path: `${base}/browser-capture/runs/${id(form, "run_id")}/tasks/${taskId}/attempts`,
      method: "POST", idempotencyKey: `browser-capture:${taskId}:v${taskVersion}`,
      body: {
        expected_task_version: taskVersion,
        surface_release_id: id(form, "surface_release_id"),
        egress_endpoint_id: id(form, "egress_endpoint_id"),
        profile_version_id: id(form, "profile_version_id"),
        requested_not_before: new Date(Date.now() + 5_000).toISOString()
      }
    };
  }
  if (command === "submit_report") return {
    path: `${base}/external-data/reports/${id(form, "report_id")}/submit`, method: "POST"
  };
  if (command === "create_connector_report") return {
    path: `${base}/external-data/connector-reports`, method: "POST", body: {
      campaign_id: id(form, "campaign_id"),
      projection_batch_id: id(form, "projection_batch_id"),
      title: field(form, "title"), summary: optional(form, "summary") || ""
    }
  };
  if (command === "create_official_report") return {
    path: `${base}/external-data/official-reports`, method: "POST", body: {
      campaign_id: id(form, "campaign_id"), import_id: id(form, "import_id"),
      customer_fields: lines(form.get("customer_fields")),
      title: field(form, "title"), summary: optional(form, "summary") || ""
    }
  };
  if (command === "create_attribution_report") return {
    path: `${base}/external-data/attribution-reports`, method: "POST", body: {
      campaign_id: id(form, "campaign_id"),
      attribution_snapshot_id: id(form, "attribution_snapshot_id"),
      title: field(form, "title"), summary: optional(form, "summary") || ""
    }
  };
  if (command === "decide_report") return {
    path: `${base}/external-data/reports/${id(form, "report_id")}/decide`, method: "POST", body: {
      snapshot_hash: field(form, "snapshot_hash"), decision: field(form, "decision"),
      reason: field(form, "reason"), review_evidence: {},
      idempotency_key: field(form, "idempotency_key")
    }
  };
  throw new Error("不支持的操作命令。");
}

function field(form: FormData, name: string): string {
  const value = String(form.get(name) || "").trim();
  if (!value) throw new Error(`${name} 不能为空。`);
  return value;
}
function optional(form: FormData, name: string): string | null {
  return String(form.get(name) || "").trim() || null;
}
function id(form: FormData, name: string): string {
  const value = field(form, name);
  if (!/^[0-9a-f-]{36}$/i.test(value)) throw new Error(`${name} 不是有效 ID。`);
  return value;
}
function integer(form: FormData, name: string): number {
  const value = Number(field(form, name));
  if (!Number.isSafeInteger(value)) throw new Error(`${name} 必须是整数。`);
  return value;
}
function json(form: FormData, name: string): Record<string, unknown> {
  const result = parseJsonObject(form.get(name), name);
  if (!result.ok) throw new Error(result.error);
  return result.data;
}
function successLabel(command: string): string {
  return ({
    install_definition: "Connector 定义已创建。", approve_definition: "Connector 定义已批准。",
    create_connection: "连接已创建。", create_scope: "采集范围已创建。",
    set_connection_status: "连接状态已更新。",
    rotate_connection_secret: "连接已切换到指定密钥版本。",
    test_connection: "连接测试已进入队列。",
    start_sync: "同步任务已进入队列。", create_policy: "归因策略已启用。",
    cancel_sync: "同步取消请求已提交。",
    create_collector: "一方事件采集端已创建。", create_snapshot: "归因快照已生成。",
    create_surface: "消费者界面版本已创建。",
    approve_surface: "消费者界面版本已批准。",
    retire_surface: "消费者界面版本已停用；请发布新版本后恢复采集。",
    set_egress_status: "澳洲出口状态已更新。",
    test_egress: "澳洲出口测试已进入队列。",
    approve_profile: "浏览器画像已批准。", create_profile: "浏览器画像已创建。",
    register_browser_sampling_input: "消费者界面采样输入已注册，可在观测与统计中创建 Suite。",
    register_browser_runtime_option: "消费者界面运行选项已注册，请在观测与统计中创建并批准准入策略。",
    enqueue_browser_capture: "消费者界面采集已进入队列。",
    create_connector_report: "Connector 数据报告草稿已创建。",
    create_official_report: "官方数据报告草稿已创建。",
    create_attribution_report: "归因报告草稿已创建。",
    submit_report: "外部数据报告已提交审核。",
    decide_report: "外部数据报告审核已记录。"
  } as Record<string, string>)[command] || "操作已完成。";
}
