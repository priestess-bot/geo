import type { ReactNode } from "react";

import "./globals.css";

export const metadata = {
  title: "GEO 澳大利亚客户工作台",
  description: "澳大利亚 AI 搜索可见度与试点交付工作台"
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body>{children}</body>
    </html>
  );
}
