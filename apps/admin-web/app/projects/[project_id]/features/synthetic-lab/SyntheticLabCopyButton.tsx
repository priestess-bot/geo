"use client";

import { useState } from "react";

import styles from "./SyntheticLab.module.css";

export function SyntheticLabCopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  async function copyText() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false);
    }
  }

  return (
    <button
      aria-label="复制最终文案"
      className={styles.copyButton}
      onClick={copyText}
      title="复制最终文案"
      type="button"
    >
      {copied ? "已复制" : "复制"}
    </button>
  );
}
