import type { ReactNode } from "react";

import "./globals.css";

export const metadata = {
  title: "GENO 工程进展 Dashboard",
  description: "GENO AU 首发项目开发进展、工程审计、测试门禁和下一步行动看板"
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body>{children}</body>
    </html>
  );
}
