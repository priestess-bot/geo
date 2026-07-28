"use client";

import { useEffect, useState } from "react";

export function DifyConsoleLink({
  className = "button secondary",
  consoleUrl,
  label = "打开 Dify 工作流"
}: {
  className?: string;
  consoleUrl: string | null | undefined;
  label?: string;
}) {
  const [href, setHref] = useState<string | null>(null);

  useEffect(() => {
    setHref(resolveDifyConsoleUrl(consoleUrl));
  }, [consoleUrl]);

  if (!href) return null;
  return <a className={className} href={href} rel="noreferrer" target="_blank">{label}</a>;
}

function resolveDifyConsoleUrl(consoleUrl: string | null | undefined): string | null {
  if (!consoleUrl) return null;
  try {
    const target = new URL(consoleUrl);
    const isLocalConsole = target.hostname === "127.0.0.1"
      || target.hostname === "localhost"
      || target.hostname === "::1";
    if (isLocalConsole) target.hostname = window.location.hostname;
    return target.toString();
  } catch {
    return null;
  }
}
