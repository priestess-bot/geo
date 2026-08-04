"use client";

import { useActionState, useEffect, useState } from "react";

import { saveChannelStyleAction } from "./syntheticLabResourceActions";
import { SyntheticActionFeedback } from "./SyntheticActionFeedback";
import {
  initialSyntheticActionState,
  syntheticChannels,
  type ChannelStyle,
  type SyntheticChannel
} from "./syntheticLabTypes";
import { channelLabel } from "./SyntheticLabUI";
import styles from "./SyntheticLab.module.css";

export function SyntheticChannelStyleWorkspace({
  canContribute,
  commandKey: initialCommandKey,
  initialStyles,
  projectId
}: {
  canContribute: boolean;
  commandKey: string;
  initialStyles: ChannelStyle[];
  projectId: string;
}) {
  const [stylesByChannel, setStylesByChannel] = useState(
    () => new Map(initialStyles.map((item) => [item.channel, item]))
  );
  const [channel, setChannel] = useState<SyntheticChannel>(
    stylesByChannel.has("reddit") ? "reddit" : syntheticChannels[0]
  );
  const [directive, setDirective] = useState(stylesByChannel.get(channel)?.directive || "");
  const [commandKey, setCommandKey] = useState(initialCommandKey);
  const [state, action, pending] = useActionState(saveChannelStyleAction, initialSyntheticActionState);
  const current = stylesByChannel.get(channel) || null;

  useEffect(() => {
    setDirective(stylesByChannel.get(channel)?.directive || "");
  }, [channel, stylesByChannel]);

  useEffect(() => {
    if (!state.channelStyle) return;
    setStylesByChannel((items) => new Map(items).set(state.channelStyle!.channel, state.channelStyle!));
    setDirective(state.channelStyle.directive);
    setCommandKey(`channel-style:${crypto.randomUUID()}`);
  }, [state.channelStyle, state.responseToken]);

  return (
    <section className={styles.styleWorkspace}>
      <header className={styles.styleHeader}>
        <div><p>渠道风格</p><h3>九渠道手工风格设置</h3></div>
        <span>en-AU · 版本化保存</span>
      </header>
      <div className={styles.styleLayout}>
        <nav className={styles.channelRail} aria-label="渠道风格列表">
          {syntheticChannels.map((item) => {
            const configured = stylesByChannel.get(item);
            return (
              <button
                className={item === channel ? styles.channelActive : ""}
                key={item}
                onClick={() => setChannel(item)}
                type="button"
              >
                <strong>{channelLabel(item)}</strong>
                <span>{configured ? `版本 ${configured.version_number}` : "待填写"}</span>
              </button>
            );
          })}
        </nav>
        <form action={action} className={styles.styleEditor}>
          <input name="project_id" type="hidden" value={projectId} />
          <input name="channel" type="hidden" value={channel} />
          <input name="expected_current_version" type="hidden" value={current?.version_number || 0} />
          <input name="idempotency_key" type="hidden" value={commandKey} />
          <div className={styles.styleEditorTitle}>
            <div><span>{channelLabel(channel)}</span><h4>生成时使用的风格提示词</h4></div>
            <span className={styles.manualPreset}>手工初始预设 · 待样本校准</span>
          </div>
          <label>
            <span>风格说明</span>
            <textarea
              name="directive"
              onChange={(event) => setDirective(event.target.value)}
              required
              rows={18}
              value={directive}
            />
            <small>保存后生成任务会冻结新版本；已经开始的任务继续使用原版本。</small>
          </label>
          <div className={styles.styleSaveRow}>
            <button disabled={!canContribute || pending || !directive.trim()} type="submit">
              {pending ? "正在保存…" : "保存为新版本"}
            </button>
            {current ? <span>当前哈希 {current.style_hash.slice(0, 12)}</span> : null}
          </div>
          <SyntheticActionFeedback state={state} />
        </form>
      </div>
    </section>
  );
}
