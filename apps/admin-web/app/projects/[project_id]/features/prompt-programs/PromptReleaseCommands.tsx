"use client";

import { useActionState } from "react";

import {
  approvePromptReleaseAction,
  bindPromptReleaseAction,
  diffPromptReleaseAction,
  freezePromptReleaseAction,
  retirePromptReleaseAction,
  enqueuePromptTestAction
} from "./promptProgramActions";
import { PromptActionFeedback } from "./PromptActionFeedback";
import {
  initialPromptActionState,
  type PromptLoadProblem,
  type PromptProgramBindingOption,
  type PromptProgramRelease,
  type PromptTestRuntimeOption
} from "./promptProgramTypes";
import styles from "./PromptPrograms.module.css";

type CommandKeys = Readonly<{
  approve: string;
  bind: string;
  diff: string;
  freeze: string;
  retire: string;
  test: string;
}>;

export function PromptReleaseCommands({
  actorIdentityId,
  baselineReleases,
  bindingProblem,
  canApprove,
  canContribute,
  commandKeys,
  currentBinding,
  projectId,
  release,
  runtimeOptions,
  runtimeProblem
}: {
  actorIdentityId: string;
  baselineReleases: PromptProgramRelease[];
  bindingProblem?: PromptLoadProblem;
  canApprove: boolean;
  canContribute: boolean;
  commandKeys: CommandKeys;
  currentBinding: PromptProgramBindingOption | null;
  projectId: string;
  release: PromptProgramRelease;
  runtimeOptions: PromptTestRuntimeOption[];
  runtimeProblem?: PromptLoadProblem;
}) {
  const [testState, testAction, testPending] = useActionState(
    enqueuePromptTestAction,
    initialPromptActionState
  );
  const [approveState, approveAction, approvePending] = useActionState(
    approvePromptReleaseAction,
    initialPromptActionState
  );
  const [freezeState, freezeAction, freezePending] = useActionState(
    freezePromptReleaseAction,
    initialPromptActionState
  );
  const [retireState, retireAction, retirePending] = useActionState(
    retirePromptReleaseAction,
    initialPromptActionState
  );
  const [bindState, bindAction, bindPending] = useActionState(
    bindPromptReleaseAction,
    initialPromptActionState
  );
  const [diffState, diffAction, diffPending] = useActionState(
    diffPromptReleaseAction,
    initialPromptActionState
  );
  const status = release.state.status;
  const hasApprovedRuntime = runtimeOptions.length > 0 && !runtimeProblem;
  const canTest = canContribute && status === "draft" && hasApprovedRuntime;
  const selfOwned = actorIdentityId === release.owner_id;
  const canApproveRelease = canApprove && status === "tested" && !selfOwned;
  const canFreeze = canApprove && status === "approved";
  const canRetire = canApprove && status === "frozen";
  const bindingInventoryAvailable = !bindingProblem;
  const canBind = canApprove && status === "frozen" && bindingInventoryAvailable;
  const canDiff = canContribute
    && (status === "draft" || status === "tested")
    && baselineReleases.length > 0;

  return (
    <div className={styles.commandStack}>
      <section className={styles.commandSection} aria-labelledby="prompt-test-heading">
        <header><h4 id="prompt-test-heading">测试执行</h4><StatusPill value={status} /></header>
        <form action={testAction} className={styles.commandForm}>
          <ReleaseHiddenFields
            idempotencyKey={commandKeys.test}
            projectId={projectId}
            release={release}
          />
          <input name="test_set_id" type="hidden" value={release.test_set_id} />
          <input name="test_set_version" type="hidden" value={release.test_set_version} />
          <input name="test_set_hash" type="hidden" value={release.test_set_hash} />
          <div className={styles.commandGrid}>
            <label>
              <span>已批准运行时</span>
              <select disabled={!canTest || testPending} name="runtime_selection_id" required>
                {runtimeOptions.length ? runtimeOptions.map((item) => (
                  <option key={item.runtime_selection_id} value={item.runtime_selection_id}>
                    {runtimeLabel(item)}
                  </option>
                )) : (
                  <option value="">无已批准运行时</option>
                )}
              </select>
            </label>
            <button disabled={!canTest || testPending} title={testDisabledReason(canContribute, status, hasApprovedRuntime)} type="submit">
              {testPending ? "排队中..." : "运行固定测试集"}
            </button>
          </div>
          {!hasApprovedRuntime ? (
            <p className={styles.commandNotice} role="status">
              {runtimeProblem?.detail || "当前项目没有支持 Prompt 固定测试的已批准运行时。"}
            </p>
          ) : null}
          <PromptActionFeedback state={testState} />
        </form>
      </section>

      <section className={styles.commandSection} aria-labelledby="prompt-governance-heading">
        <header><h4 id="prompt-governance-heading">批准与冻结</h4></header>
        <div className={styles.governanceRow}>
          <form action={approveAction}>
            <ReleaseHiddenFields
              idempotencyKey={commandKeys.approve}
              projectId={projectId}
              release={release}
            />
            <button
              disabled={!canApproveRelease || approvePending}
              title={approveDisabledReason(canApprove, status, selfOwned)}
              type="submit"
            >
              {approvePending ? "批准中..." : "批准"}
            </button>
          </form>
          <form action={freezeAction}>
            <ReleaseHiddenFields
              idempotencyKey={commandKeys.freeze}
              projectId={projectId}
              release={release}
            />
            <button
              className="secondary"
              disabled={!canFreeze || freezePending}
              title={freezeDisabledReason(canApprove, status)}
              type="submit"
            >
              {freezePending ? "冻结中..." : "冻结"}
            </button>
          </form>
        </div>
        <PromptActionFeedback state={approveState} />
        <PromptActionFeedback state={freezeState} />
        <form action={retireAction} className={styles.retirementForm}>
          <ReleaseHiddenFields
            idempotencyKey={commandKeys.retire}
            projectId={projectId}
            release={release}
          />
          <label>
            <input
              disabled={!canRetire || retirePending}
              name="confirm_retirement"
              required
              type="checkbox"
              value="confirmed"
            />
            <span>停止该发布版本的新运行时解析</span>
          </label>
          <button
            className={styles.retireButton}
            disabled={!canRetire || retirePending}
            title={retireDisabledReason(canApprove, status)}
            type="submit"
          >
            {retirePending ? "退役中..." : "退役发布版本"}
          </button>
        </form>
        <PromptActionFeedback state={retireState} />
      </section>

      <section className={styles.commandSection} aria-labelledby="prompt-binding-heading">
        <header><h4 id="prompt-binding-heading">运行时绑定</h4></header>
        <form action={bindAction} className={styles.commandForm}>
          <input name="project_id" type="hidden" value={projectId} />
          <input name="program_id" type="hidden" value={release.program_id} />
          <input name="release_id" type="hidden" value={release.id} />
          <input name="idempotency_key" type="hidden" value={commandKeys.bind} />
          <input name="purpose" type="hidden" value={release.purpose} />
          <input name="expected_version" type="hidden" value={currentBinding?.binding_version || 0} />
          <div className={styles.commandGrid}>
            <label>
              <span>用途（由冻结发布版本固定）</span>
              <span className={styles.readOnlyValue}>{release.purpose}</span>
            </label>
            <label>
              <span>当前绑定版本</span>
              <span className={styles.readOnlyValue}>{currentBinding?.binding_version || 0}</span>
            </label>
            <button disabled={!canBind || bindPending} title={bindDisabledReason(canApprove, status, bindingInventoryAvailable)} type="submit">
              {bindPending ? "绑定中..." : "绑定冻结发布版本"}
            </button>
          </div>
          {bindingProblem ? <p className={styles.commandNotice} role="status">{bindingProblem.detail}</p> : null}
          <PromptActionFeedback state={bindState} />
        </form>
      </section>

      <section className={styles.commandSection} aria-labelledby="prompt-diff-heading">
        <header><h4 id="prompt-diff-heading">固定输入差异</h4><span>候选版本 v{release.version}</span></header>
        <form action={diffAction} className={styles.commandForm}>
          <ReleaseHiddenFields
            idempotencyKey={commandKeys.diff}
            projectId={projectId}
            release={release}
          />
          <div className={styles.diffFormGrid}>
            <label>
              <span>已批准 / 已冻结基线</span>
              <select disabled={!canDiff || diffPending} name="baseline_release_id" required>
                {baselineReleases.length ? baselineReleases.map((item) => (
                  <option key={item.id} value={item.id}>v{item.version} · {item.state.status}</option>
                )) : <option value="">无可用基线</option>}
              </select>
            </label>
            <label className={styles.fixedInputField}>
              <span>固定输入（JSON 对象）</span>
              <textarea defaultValue="{}" disabled={!canDiff || diffPending} name="fixed_variables" required spellCheck={false} />
            </label>
            <button disabled={!canDiff || diffPending} title={diffDisabledReason(canContribute, status, baselineReleases.length)} type="submit">
              {diffPending ? "比较中..." : "比较版本"}
            </button>
          </div>
          <PromptActionFeedback state={diffState} />
        </form>
      </section>
    </div>
  );
}

function ReleaseHiddenFields({
  idempotencyKey,
  projectId,
  release
}: {
  idempotencyKey: string;
  projectId: string;
  release: PromptProgramRelease;
}) {
  return (
    <>
      <input name="project_id" type="hidden" value={projectId} />
      <input name="program_id" type="hidden" value={release.program_id} />
      <input name="release_id" type="hidden" value={release.id} />
      <input name="expected_version" type="hidden" value={release.state.version} />
      <input name="idempotency_key" type="hidden" value={idempotencyKey} />
    </>
  );
}

function StatusPill({ value }: { value: string }) {
  return <span className={`${styles.statusPill} ${styles[`status_${value}`] || ""}`}>{statusLabel(value)}</span>;
}

function statusLabel(value: string): string {
  return { draft: "草稿", tested: "已测试", approved: "已批准", frozen: "已冻结", retired: "已退役" }[value] || value;
}

function testDisabledReason(
  canContribute: boolean,
  status: string,
  hasApprovedRuntime: boolean
): string {
  if (!canContribute) return "当前角色不能运行测试";
  if (status !== "draft") return "仅草稿发布版本可以运行测试";
  return hasApprovedRuntime ? "" : "需要项目级已批准 Prompt 测试运行时";
}

function runtimeLabel(item: PromptTestRuntimeOption): string {
  return `${item.provider} · ${item.configured_model} · ${item.adapter_release_id}`;
}

function approveDisabledReason(canApprove: boolean, status: string, selfOwned: boolean): string {
  if (!canApprove) return "仅项目负责人或管理员可以批准";
  if (selfOwned) return "发布版本创建者不能批准自己的发布版本";
  return status === "tested" ? "" : "仅已测试发布版本可以批准";
}

function freezeDisabledReason(canApprove: boolean, status: string): string {
  if (!canApprove) return "仅项目负责人或管理员可以冻结";
  return status === "approved" ? "" : "仅已批准发布版本可以冻结";
}

function retireDisabledReason(canApprove: boolean, status: string): string {
  if (!canApprove) return "仅项目负责人或管理员可以退役";
  return status === "frozen" ? "" : "仅已冻结发布版本可以退役";
}

function bindDisabledReason(
  canApprove: boolean,
  status: string,
  inventoryAvailable: boolean
): string {
  if (!canApprove) return "仅项目负责人或管理员可以绑定";
  if (status !== "frozen") return "仅已冻结发布版本可以绑定";
  return inventoryAvailable ? "" : "当前绑定目录不可用";
}

function diffDisabledReason(canContribute: boolean, status: string, baselines: number): string {
  if (!canContribute) return "当前角色不能执行差异比较";
  if (status !== "draft" && status !== "tested") return "候选版本必须为草稿或已测试";
  return baselines > 0 ? "" : "需要更早的已批准或已冻结基线";
}
