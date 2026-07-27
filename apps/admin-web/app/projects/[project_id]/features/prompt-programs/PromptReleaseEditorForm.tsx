"use client";

import { useActionState, useId, useState } from "react";

import {
  createPromptProgramAction,
  createPromptReleaseAction
} from "./promptProgramActions";
import { PromptActionFeedback } from "./PromptActionFeedback";
import type { PromptBootstrapCatalog } from "./promptBootstrapTypes";
import {
  auxiliaryPromptProgramKinds,
  initialPromptActionState,
  primaryPromptProgramKinds,
  promptProgramKinds,
  workflowPromptProgramKinds,
  type PromptProgramKind,
  type PromptProgramSummary
} from "./promptProgramTypes";
import styles from "./PromptPrograms.module.css";

export function PromptReleaseEditorForm({
  catalog,
  disabled,
  expectedVersion,
  idempotencyKey,
  mode,
  programId,
  programKind,
  programPurpose,
  projectId
}: {
  catalog: PromptBootstrapCatalog | null;
  disabled: boolean;
  expectedVersion: number;
  idempotencyKey: string;
  mode: "program" | "release";
  programId?: string;
  programKind?: PromptProgramSummary["program_kind"];
  programPurpose?: string;
  projectId: string;
}) {
  const action = mode === "program" ? createPromptProgramAction : createPromptReleaseAction;
  const [state, formAction, pending] = useActionState(action, initialPromptActionState);
  const testSetLineageId = useId();
  const creatingProgram = mode === "program";
  const [selectedKind, setSelectedKind] = useState<PromptProgramKind | null>(() => (
    creatingProgram
      ? promptProgramKinds[0]
      : promptProgramKinds.find((kind) => kind === programKind) || null
  ));
  const inventory = selectedKind
    ? catalog?.items.find((item) => item.program_kind === selectedKind) || null
    : null;
  const purposeMatchesProgram = creatingProgram || inventory?.purpose === programPurpose;
  const selectionAvailable = Boolean(inventory && purposeMatchesProgram);
  const formDisabled = disabled || pending || !selectionAvailable;
  const testSetSelection = inventory
    ? `${inventory.test_set_id}:${inventory.test_set_version}:${inventory.test_set_hash}`
    : "";
  return (
    <form action={formAction} className={styles.editorForm}>
      <input name="project_id" type="hidden" value={projectId} />
      <input name="idempotency_key" type="hidden" value={idempotencyKey} />
      <input name="expected_version" type="hidden" value={expectedVersion} />
      {programId ? <input name="program_id" type="hidden" value={programId} /> : null}
      {!creatingProgram ? <input name="program_kind" type="hidden" value={selectedKind || ""} /> : null}
      <input name="purpose" type="hidden" value={inventory?.purpose || ""} />
      <input name="test_set_id" type="hidden" value={inventory?.test_set_id || ""} />
      <input name="test_set_version" type="hidden" value={inventory?.test_set_version || ""} />
      <input name="test_set_hash" type="hidden" value={inventory?.test_set_hash || ""} />
      <input name="variable_schema_version" type="hidden" value={inventory?.variable_schema_version || ""} />
      <input name="variable_schema" type="hidden" value={JSON.stringify(inventory?.variable_schema || {})} />
      <input name="input_schema_version" type="hidden" value={inventory?.input_schema_version || ""} />
      <input name="input_schema" type="hidden" value={JSON.stringify(inventory?.input_schema || {})} />
      <input name="output_schema_version" type="hidden" value={inventory?.output_schema_version || ""} />
      <input name="output_schema" type="hidden" value={JSON.stringify(inventory?.output_schema || {})} />
      <input
        name="application_output_schema_version"
        type="hidden"
        value={inventory?.application_output_schema_version || ""}
      />
      <input
        name="application_output_schema"
        type="hidden"
        value={JSON.stringify(inventory?.application_output_schema || {})}
      />
      <input name="model_policy_version" type="hidden" value={inventory?.model_policy_version || ""} />
      <input name="model_policy" type="hidden" value={JSON.stringify(inventory?.model_policy || {})} />
      <fieldset disabled={formDisabled}>
        <legend>{creatingProgram ? "创建 Prompt 程序与 v1" : `创建 v${expectedVersion + 1}`}</legend>
        <div className={styles.formGrid}>
          {creatingProgram ? (
            <label>
              <span>Prompt 程序类型</span>
              <select
                name="program_kind"
                onChange={(event) => {
                  const next = promptProgramKinds.find((kind) => kind === event.target.value);
                  if (next) setSelectedKind(next);
                }}
                required
                value={selectedKind || ""}
              >
                <optgroup label="主类型（业务）">
                  {primaryPromptProgramKinds.map((kind) => (
                    <option key={kind} value={kind}>{kindLabel(kind)}</option>
                  ))}
                </optgroup>
                <optgroup label="内部辅助（系统工作流）">
                  {auxiliaryPromptProgramKinds.map((kind) => (
                    <option key={kind} value={kind}>{kindLabel(kind)}</option>
                  ))}
                </optgroup>
                <optgroup label="问题与内容生成">
                  {workflowPromptProgramKinds.map((kind) => (
                    <option key={kind} value={kind}>{kindLabel(kind)}</option>
                  ))}
                </optgroup>
                <option disabled value="reference_translation">参考翻译（预留，暂不可用）</option>
              </select>
            </label>
          ) : (
            <label>
              <span>Prompt 程序类型（固定）</span>
              <span className={styles.readOnlyValue}>{selectedKind ? kindLabel(selectedKind) : "不可用"}</span>
            </label>
          )}
          <label className={styles.doubleField}>
            <span>用途（由 Prompt 程序类型固定）</span>
            <span className={styles.readOnlyValue}>{inventory?.purpose || "基线目录不可用"}</span>
          </label>
        </div>

        {!selectionAvailable ? (
          <p className={styles.editorNotice} role="alert">
            {inventory
              ? "当前程序的用途与冻结目录不一致，不能从此表单创建新发布版本。"
              : "冻结 Prompt 基线目录不可用，创建操作保持关闭。"}
          </p>
        ) : null}

        <div className={styles.templateGrid}>
          <label>
            <span>系统模板</span>
            <textarea maxLength={100000} name="system_template" required spellCheck={false} />
          </label>
          <label>
            <span>用户模板</span>
            <textarea maxLength={100000} name="user_template" required spellCheck={false} />
          </label>
        </div>

        <details className={styles.contractFields}>
          <summary>冻结 Schema、模型策略与测试集</summary>
          <div className={styles.formGrid}>
            <label>
              <span>变量 / 输入 Schema</span>
              <span className={styles.readOnlyValue}>
                {inventory
                  ? `${inventory.variable_schema_version} · ${inventory.input_schema_version}`
                  : "目录不可用"}
              </span>
            </label>
            <label className={styles.doubleField}>
              <span>Provider / 应用输出 Schema</span>
              <span className={styles.readOnlyValue}>
                {inventory
                  ? `${inventory.output_schema_version} · ${inventory.application_output_schema_version}`
                  : "目录不可用"}
              </span>
              <small className={styles.inventoryLineage}>
                {inventory
                  ? `Provider ${inventory.output_schema_hash} · 应用 ${inventory.application_output_schema_hash}`
                  : "没有可提交的双 Schema 标识。"}
              </small>
            </label>
            <label>
              <span>模型策略（目录固定）</span>
              <span className={styles.readOnlyValue}>{inventory?.model_policy_version || "目录不可用"}</span>
              <small className={styles.inventoryLineage}>
                {inventory ? `SHA-256 ${inventory.model_policy_hash}` : "没有可提交的模型策略。"}
              </small>
            </label>
            <label className={styles.doubleField}>
              <span>固定测试集（目录）</span>
              <select
                aria-describedby={testSetLineageId}
                defaultValue={testSetSelection}
                key={testSetSelection}
              >
                {inventory ? (
                  <option value={testSetSelection}>{testSetLabel(inventory)}</option>
                ) : <option value="">目录不可用</option>}
              </select>
              <small id={testSetLineageId} className={styles.inventoryLineage}>
                {inventory ? `SHA-256 ${inventory.test_set_hash}` : "没有可提交的测试集身份。"}
              </small>
            </label>
            <label>
              <span>编译器版本</span>
              <input defaultValue="geo-prompt-compiler-v2" maxLength={100} name="compiler_version" required />
            </label>
          </div>
        </details>
      </fieldset>
      <div className={styles.formActions}>
        <button disabled={formDisabled} type="submit">
          {pending ? "提交中..." : creatingProgram ? "创建 v1" : `创建 v${expectedVersion + 1}`}
        </button>
      </div>
      <PromptActionFeedback state={state} />
    </form>
  );
}

function testSetLabel(item: PromptBootstrapCatalog["items"][number]): string {
  return `${kindLabel(item.program_kind)} · 固定回归 ${item.fixtures.length} cases · v${item.test_set_version}`;
}

function kindLabel(kind: PromptProgramKind): string {
  const labels: Record<PromptProgramKind, string> = {
    generation: "生成",
    claim_extraction: "Claim 抽取",
    conflict_check: "冲突检查",
    revision: "修订",
    style_judge: "风格评审",
    arbiter: "仲裁",
    metric_judge: "指标评审",
    recommendation: "建议生成",
    style_profile: "风格画像",
    offline_answer: "离线实验回答",
    question_generation: "测试问题生成",
    rag_grounding: "RAG 问题约束",
    placement_generation: "投放内容生成",
    placement_simulation: "投放 Prompt 仿真"
  };
  return `${labels[kind]} · ${kind}`;
}
