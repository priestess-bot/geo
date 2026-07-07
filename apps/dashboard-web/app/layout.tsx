import type { ReactNode } from "react";

import "./globals.css";

export const metadata = {
  title: "GEO Dashboard 已合并",
  description: "独立工程看板已合并到 Admin Web /development-board"
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body>{children}</body>
    </html>
  );
}
