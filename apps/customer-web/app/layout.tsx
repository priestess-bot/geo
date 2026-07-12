import type { ReactNode } from "react";

import "./globals.css";

export const metadata = {
  title: "GEO 客户工作台",
  description: "AI 搜索可见度、证据、报告与行动交付门户"
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body>{children}</body>
    </html>
  );
}
