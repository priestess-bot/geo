"use server";

import { runtimeRequest } from "../../runtime";
import {
  isCatalogProject,
  type CatalogProject,
  type CreateProjectRequest
} from "../projectTypes";

export type CreateProjectActionState = Readonly<{
  kind: "idle" | "success" | "error";
  message?: string;
  project?: CatalogProject;
  status?: number;
  correlationId?: string;
}>;

export const initialCreateProjectState: CreateProjectActionState = { kind: "idle" };

export async function createProjectAction(
  _previousState: CreateProjectActionState,
  formData: FormData
): Promise<CreateProjectActionState> {
  const name = String(formData.get("name") || "").trim();
  if (!name || name.length > 200) {
    return { kind: "error", status: 422, message: "项目名称需为 1 到 200 个字符。" };
  }
  const payload: CreateProjectRequest = { name };
  const response = await runtimeRequest<CatalogProject>("/v1/projects", {
    method: "POST",
    body: payload
  });
  if (!response.ok) {
    return {
      kind: "error",
      status: response.status,
      message: `${failureLabel(response.status)}${response.error || "项目创建失败。"}`,
      ...(response.problem.correlation_id
        ? { correlationId: response.problem.correlation_id }
        : {})
    };
  }
  if (!isCatalogProject(response.data)) {
    return {
      kind: "error",
      status: 502,
      message: "项目接口返回了无法识别的响应。",
      ...(response.response.correlationId
        ? { correlationId: response.response.correlationId }
        : {})
    };
  }
  return {
    kind: "success",
    message: "项目已创建。成员和客户邀请尚未创建，请在项目详情中显式配置。",
    project: response.data
  };
}

function failureLabel(status: number | undefined): string {
  if (status === 401) return "登录已失效：";
  if (status === 403) return "权限不足：";
  if (status === 409) return "状态冲突：";
  if (status === 422) return "输入无效：";
  return "";
}
