import { randomUUID } from "node:crypto";
import Link from "next/link";

import type { ManagedMemberRole } from "../../memberTypes";
import {
  AuthorizationCommands,
  CreateAuthorizationForm,
  FreezeSuiteForm,
  ProfileCommands
} from "./SyntheticLabGovernanceForms";
import {
  StyleCollectionAdmissionForm,
  StyleProfileBuildForm
} from "./SyntheticLabJobForms";
import {
  CreateReviewCaseForm,
  CreateReviewSuiteForm,
  CreateStyleProfileForm,
  CreateStyleSourceForm,
  ManualImportApprovalForm,
  ManualSampleImportForm
} from "./SyntheticLabResourceForms";
import {
  EmptyState,
  LoadProblem,
  SectionHeading,
  StatusBadge,
  SyntheticBoundaryBand,
  ViewHeader,
  accessModeLabel,
  caseModeLabel,
  channelLabel,
  syntheticHref
} from "./SyntheticLabUI";
import type {
  ReviewCase,
  ReviewSuite,
  StyleProfile,
  StyleSource,
  SyntheticWorkspaceData
} from "./syntheticLabTypes";
import styles from "./SyntheticLab.module.css";

export function SyntheticStyleView({
  actorIdentityId,
  canApprove,
  canContribute,
  data,
  projectId
}: {
  actorIdentityId: string;
  canApprove: boolean;
  canContribute: boolean;
  data: SyntheticWorkspaceData;
  projectId: string;
}) {
  return (
    <div className={styles.viewStack}>
      <ViewHeader
        eyebrow="低频资源管理"
        title="风格来源、样本与画像"
        description="这里维护澳洲英文表达证据。日常生成文案不需要重复进入本页。"
        action={<a className={styles.secondaryAction} href={syntheticHref(projectId, "generate")}>返回生成页</a>}
      />

      <section className={styles.metricStrip} aria-label="风格资源摘要">
        <div><span>风格来源</span><strong>{data.sources.total}</strong></div>
        <div><span>人工导入预览</span><strong>{data.importPreviews.total}</strong></div>
        <div><span>已批准样本</span><strong>{data.inventory.samples.length}</strong></div>
        <div><span>风格画像</span><strong>{data.profiles.total}</strong></div>
      </section>

      <section className={styles.section}>
        <SectionHeading eyebrow="来源与采集" title="风格来源" aside={<span>澳洲英文 · 9 个渠道</span>} />
        {data.sourcesProblem ? <LoadProblem problem={data.sourcesProblem} title="风格来源加载失败" /> : null}
        {data.authorizationsProblem ? <LoadProblem problem={data.authorizationsProblem} title="采集授权加载失败" /> : null}
        {data.loginSecretsProblem ? <LoadProblem problem={data.loginSecretsProblem} title="登录密钥引用加载失败" /> : null}
        <div className={styles.toolDisclosureList}>
          <details><summary><strong>新增风格来源</strong><span>登记公开页面、登录页面或人工导入来源</span></summary><CreateStyleSourceForm canContribute={canContribute} commandKey={commandKey("source-create")} projectId={projectId} /></details>
          <details><summary><strong>采集公开或登录页面</strong><span>仅显示已经完成授权准入的来源</span></summary><StyleCollectionAdmissionForm authorizations={data.authorizations.items} canContribute={canContribute} commandKey={commandKey("style-collection-admit")} loginSecrets={data.loginSecrets} projectId={projectId} sources={data.sources.items} /></details>
        </div>
        {!data.sourcesProblem && data.sources.items.length === 0 ? (
          <EmptyState title="还没有风格来源" description="先登记一个来源，再采集或导入样本。" />
        ) : data.sources.items.length ? <StyleSourceTable items={data.sources.items} /> : null}
      </section>

      <section className={styles.section}>
        <SectionHeading eyebrow="人工样本" title="导入与独立复核" aside={<span>支持 text、CSV、JSONL</span>} />
        {data.importPreviewsProblem ? (
          <LoadProblem problem={data.importPreviewsProblem} title="人工导入暂不可用" />
        ) : null}
        {data.importPreviewProblem ? <LoadProblem problem={data.importPreviewProblem} title="导入预览详情加载失败" /> : null}
        <details className={styles.primaryDisclosure}>
          <summary><strong>上传风格样本</strong><span>上传后先预览并去标识，再由另一位人员复核</span></summary>
          <ManualSampleImportForm canContribute={canContribute && !data.importPreviewsProblem} commandKey={commandKey("sample-import-preview")} projectId={projectId} sources={data.sources.items} />
        </details>
        {data.importPreviews.items.length ? <ImportPreviewTable data={data} projectId={projectId} /> : !data.importPreviewsProblem ? (
          <EmptyState title="暂无待复核导入" description="人工导入的预览和阻断原因会显示在这里。" />
        ) : null}
        {data.selectedImportPreview ? (
          <ManualImportApprovalForm actorIdentityId={actorIdentityId} canContribute={canContribute} commandKey={commandKey("sample-import-approve")} preview={data.selectedImportPreview} projectId={projectId} />
        ) : null}
      </section>

      <section className={styles.section}>
        <SectionHeading eyebrow="生成时使用" title="风格画像" aside={<span>冻结门槛 ≥ 200 条明审样本</span>} />
        {data.profilesProblem ? <LoadProblem problem={data.profilesProblem} title="风格画像加载失败" /> : null}
        {data.inventoryProblem ? <LoadProblem problem={data.inventoryProblem} title="风格画像依赖加载失败" /> : null}
        <details className={styles.primaryDisclosure}>
          <summary><strong>创建风格画像草稿</strong><span>选择同一渠道的明审样本和已绑定 Prompt</span></summary>
          <CreateStyleProfileForm canContribute={canContribute} commandKey={commandKey("profile-create")} inventory={data.inventory} projectId={projectId} />
        </details>
        {!data.profilesProblem && data.profiles.items.length === 0 ? (
          <EmptyState title="还没有风格画像" description="至少准备 200 条通过明审的样本后创建画像。" />
        ) : data.profiles.items.length ? (
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead><tr><th>渠道与版本</th><th>状态</th><th>构建验证</th><th>样本数</th><th>操作</th></tr></thead>
              <tbody>{data.profiles.items.map((profile) => (
                <tr key={profile.id}>
                  <td><strong>{channelLabel(profile.channel)} · 版本 {profile.version_number}</strong><code>{profile.id}</code></td>
                  <td><StatusBadge value={profile.status} /></td>
                  <td><ProfileVerification profile={profile} /></td>
                  <td>{profile.approved_sample_count}</td>
                  <td>
                    {profileNeedsRebuild(profile) ? (
                      <div className={styles.inlineNotice}><strong>仅供历史查看</strong><span>请新建版本并重新构建。</span></div>
                    ) : (
                      <div className={styles.actionStack}>
                        <ProfileCommands canApprove={canApprove} canContribute={canContribute} commandKeys={{ decision: commandKey("profile-decision"), freeze: commandKey("profile-freeze"), submit: commandKey("profile-submit") }} profile={profile} projectId={projectId} />
                        {profile.status === "draft" ? <StyleProfileBuildForm canContribute={canContribute && !data.runtimeOptionsProblem} commandKey={commandKey("profile-build")} inventory={data.inventory} profile={profile} projectId={projectId} runtimes={data.runtimeOptions.items} /> : null}
                      </div>
                    )}
                  </td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : null}
      </section>
    </div>
  );
}

export function SyntheticSuitesView({
  canApprove,
  canContribute,
  data,
  projectId
}: {
  canApprove: boolean;
  canContribute: boolean;
  data: SyntheticWorkspaceData;
  projectId: string;
}) {
  const selectedSuite = data.suites.items.find((item) => item.id === data.selectedSuiteId) || null;
  return (
    <div className={styles.viewStack}>
      <ViewHeader
        eyebrow="固定回归合同"
        title="测评套件与用例"
        description="把人物、使用场景、问题集、Fact 和风格画像固定为可重复运行的测评用例。"
        action={selectedSuite?.status === "frozen" ? <a className={styles.primaryAction} href={syntheticHref(projectId, "generate", { synthetic_suite_id: selectedSuite.id })}>用此套件生成</a> : null}
      />
      {data.suitesProblem ? <LoadProblem problem={data.suitesProblem} title="测评套件加载失败" /> : null}
      <section className={styles.section}>
        <SectionHeading title="测评套件" aside={<span>{data.suites.total} 个版本</span>} />
        <details className={styles.primaryDisclosure}>
          <summary><strong>创建测评套件</strong><span>先创建草稿，再添加用例并冻结</span></summary>
          <CreateReviewSuiteForm canContribute={canContribute} commandKey={commandKey("suite-create")} projectId={projectId} />
        </details>
        {!data.suitesProblem && data.suites.items.length === 0 ? (
          <EmptyState title="还没有测评套件" description="创建第一个套件，并加入至少一个用例。" />
        ) : data.suites.items.length ? <SuiteTable data={data} projectId={projectId} /> : null}
      </section>

      {selectedSuite ? (
        <section className={styles.section}>
          <SectionHeading
            eyebrow={`${channelLabel(selectedSuite.channel)} · 版本 ${selectedSuite.version_number}`}
            title="所选套件的用例"
            aside={<StatusBadge value={selectedSuite.status} />}
          />
          {data.casesProblem ? <LoadProblem problem={data.casesProblem} title="测评用例加载失败" /> : null}
          {selectedSuite.status === "draft" ? (
            <details className={styles.primaryDisclosure}>
              <summary><strong>新增测评用例</strong><span>填写人物、场景、主体并选择冻结证据</span></summary>
              <CreateReviewCaseForm canContribute={canContribute} commandKey={commandKey("case-create")} inventory={data.inventory} projectId={projectId} suite={selectedSuite} />
            </details>
          ) : null}
          {!data.casesProblem && data.selectedCases.items.length === 0 ? (
            <EmptyState title="此套件还没有用例" description="草稿套件至少添加一个用例后才能冻结。" />
          ) : data.selectedCases.items.length ? <CaseTable items={data.selectedCases.items} /> : null}
          <div className={styles.freezeBar}>
            <div><strong>{selectedSuite.status === "frozen" ? "套件已冻结" : "冻结后即可用于生成"}</strong><span>{data.selectedCases.items.length} 个当前用例</span></div>
            <FreezeSuiteForm canApprove={canApprove} cases={data.selectedCases.items} commandKey={commandKey("suite-freeze")} projectId={projectId} suite={selectedSuite} />
          </div>
        </section>
      ) : null}
    </div>
  );
}

export function SyntheticSettingsView({
  canApprove,
  canContribute,
  currentRole,
  data,
  projectId
}: {
  canApprove: boolean;
  canContribute: boolean;
  currentRole: ManagedMemberRole | null;
  data: SyntheticWorkspaceData;
  projectId: string;
}) {
  return (
    <div className={styles.viewStack}>
      <ViewHeader
        eyebrow="低频设置"
        title="运行时、流程绑定与采集授权"
        description="只有新增渠道、切换模型或更新工作流时需要修改本页。生成文案不需要重复审批。"
      />
      <SyntheticBoundaryBand />

      <section className={styles.section}>
        <SectionHeading eyebrow="只读状态" title="生成流程与模型运行时" />
        {data.inventoryProblem ? <LoadProblem problem={data.inventoryProblem} title="Prompt 绑定加载失败" /> : null}
        {data.runtimeOptionsProblem ? <LoadProblem problem={data.runtimeOptionsProblem} title="模型运行时加载失败" /> : null}
        <div className={styles.settingsColumns}>
          <div>
            <h5>当前 Prompt / Dify 绑定</h5>
            {data.inventory.prompt_bindings.length ? (
              <ul className={styles.simpleList}>{data.inventory.prompt_bindings.map((binding) => <li key={binding.id}><strong>{promptPurposeLabel(binding.label.split(" · ")[0])}</strong><small>{binding.label}</small></li>)}</ul>
            ) : <EmptyState title="未读取到流程绑定" description="前往 Prompt 程序页检查 Dify 发布绑定。" />}
          </div>
          <div>
            <h5>已批准模型运行时</h5>
            {data.runtimeOptions.items.length ? (
              <ul className={styles.simpleList}>{data.runtimeOptions.items.map((runtime) => <li key={runtime.selection_id}><strong>{runtime.provider} · {runtime.configured_model}</strong><small>{runtime.capture_method === "provider_api" ? "Provider API" : "代理 Grounding API"} · {runtime.allowed_purposes.length} 个用途</small></li>)}</ul>
            ) : <EmptyState title="暂无可用运行时" description="先在模型网关注册并批准运行时。" />}
          </div>
        </div>
      </section>

      <section className={styles.section}>
        <SectionHeading eyebrow="仅用于在线风格采集" title="采集授权" aside={<span>当前角色：{roleLabel(currentRole)}</span>} />
        {data.authorizationsProblem ? <LoadProblem problem={data.authorizationsProblem} title="采集授权加载失败" /> : null}
        <details className={styles.primaryDisclosure}>
          <summary><strong>新增待评估授权</strong><span>授权只控制指定渠道和适配器的在线风格采集</span></summary>
          <CreateAuthorizationForm canCreate={canApprove} commandKey={commandKey("authorization-create")} projectId={projectId} />
        </details>
        {!data.authorizationsProblem && data.authorizations.items.length === 0 ? (
          <EmptyState title="暂无采集授权" description="在线风格采集保持关闭；人工导入仍可独立使用。" />
        ) : data.authorizations.items.length ? (
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead><tr><th>渠道与适配器</th><th>状态</th><th>请求限制</th><th>有效期</th><th>操作</th></tr></thead>
              <tbody>{data.authorizations.items.map((authorization) => (
                <tr key={authorization.id}>
                  <td><strong>{channelLabel(authorization.channel)}</strong><code>{authorization.adapter_release}</code></td>
                  <td><StatusBadge value={authorization.effective_state} /></td>
                  <td>{authorization.max_requests_per_period ?? "-"} 次 / {authorization.period_seconds ?? "-"} 秒<small>最大并发 {authorization.max_concurrency ?? "-"}</small></td>
                  <td>{authorization.expires_at ? new Date(authorization.expires_at).toLocaleString("zh-CN") : "未设置"}</td>
                  <td><AuthorizationCommands authorization={authorization} canApprove={canApprove} canReassess={canContribute} commandKeys={{ decide: commandKey("authorization-decide"), reassess: commandKey("authorization-reassess"), revoke: commandKey("authorization-revoke") }} projectId={projectId} /></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : null}
      </section>
    </div>
  );
}

function StyleSourceTable({ items }: { items: StyleSource[] }) {
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead><tr><th>渠道</th><th>访问方式</th><th>状态</th><th>修订版本</th><th>来源 ID</th></tr></thead>
        <tbody>{items.map((item) => (
          <tr key={item.id}>
            <td><strong>{channelLabel(item.channel)}</strong></td>
            <td>{accessModeLabel(item.access_mode)}</td>
            <td><StatusBadge value={item.status} /></td>
            <td>第 {item.revision_number} 版</td>
            <td><code>{item.id}</code></td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

function ImportPreviewTable({ data, projectId }: { data: SyntheticWorkspaceData; projectId: string }) {
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead><tr><th>文件</th><th>状态</th><th>总行数</th><th>可选 / 阻断</th><th>操作</th></tr></thead>
        <tbody>{data.importPreviews.items.map((item) => (
          <tr key={item.id}>
            <td><strong>{item.filename}</strong><small>{channelLabel(item.channel)} · {item.import_format.toUpperCase()}</small></td>
            <td><StatusBadge value={item.status} /></td>
            <td>{item.row_count}</td>
            <td>{item.selectable_count} / {item.blocked_count}</td>
            <td><a className={styles.textLink} href={syntheticHref(projectId, "style", { synthetic_import_preview_id: item.id })}>打开复核</a></td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

function SuiteTable({ data, projectId }: { data: SyntheticWorkspaceData; projectId: string }) {
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead><tr><th>渠道与版本</th><th>状态</th><th>用例数</th><th>套件 ID</th><th>操作</th></tr></thead>
        <tbody>{data.suites.items.map((item) => (
          <tr className={item.id === data.selectedSuiteId ? styles.activeRow : undefined} key={item.id}>
            <td><strong>{channelLabel(item.channel)} · 版本 {item.version_number}</strong></td>
            <td><StatusBadge value={item.status} /></td>
            <td>{item.case_count}</td>
            <td><code>{item.id}</code></td>
            <td>
              {item.id === data.selectedSuiteId ? (
                <span aria-current="true" className={styles.currentSelection}>当前已打开</span>
              ) : (
                <Link
                  className={styles.textLink}
                  href={syntheticHref(projectId, "suites", { synthetic_suite_id: item.id })}
                  scroll={false}
                >
                  查看用例
                </Link>
              )}
            </td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

function CaseTable({ items }: { items: ReviewCase[] }) {
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead><tr><th>用例</th><th>场景模式</th><th>渠道</th><th>竞品场景</th><th>内容 ID</th></tr></thead>
        <tbody>{items.map((item) => (
          <tr key={item.id}>
            <td><strong>{item.ordinal} · {item.case_key}</strong></td>
            <td>{caseModeLabel(item.mode)}</td>
            <td>{channelLabel(item.channel)}</td>
            <td>{item.competitor_scenario ? "是" : "否"}</td>
            <td><code>{item.id}</code></td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

function ProfileVerification({ profile }: { profile: StyleProfile }) {
  if (profileNeedsRebuild(profile)) return <span className={styles.verificationBad}><strong>需要重建</strong><small>不能用于新任务</small></span>;
  if (profile.build_verification_status === "verified") return <span className={styles.verificationGood}><strong>已验证</strong><small>可用于生成</small></span>;
  return <span className={styles.verificationPending}><strong>待构建</strong><small>尚不能用于生成</small></span>;
}

function profileNeedsRebuild(profile: StyleProfile): boolean {
  return profile.rebuild_required || profile.build_verification_status === "legacy_unverified";
}

function promptPurposeLabel(value: string): string {
  return {
    "synthetic_lab.generation": "文案生成",
    "synthetic_lab.claim_extraction": "声明提取",
    "synthetic_lab.conflict_check": "知识冲突检查",
    "synthetic_lab.revision": "自动修订",
    "synthetic_lab.style_judge": "风格判定",
    "synthetic_lab.arbiter": "最终仲裁",
    "synthetic_lab.style_profile": "风格画像构建",
    "synthetic_lab.offline_answer": "离线实验回答"
  }[value] || value;
}

function roleLabel(value: ManagedMemberRole | null): string {
  const labels: Record<string, string> = {
    owner: "负责人",
    admin: "管理员",
    analyst: "分析员",
    viewer: "只读成员"
  };
  return labels[value || ""] || "未识别";
}

function commandKey(scope: string): string {
  return `synthetic-${scope}-${randomUUID()}`;
}
