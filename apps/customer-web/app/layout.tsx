import type { ReactNode } from "react";

import "./globals.css";

export const metadata = {
  title: "GENO 澳大利亚客户工作台",
  description: "澳大利亚 AI 搜索可见度与 GEO 交付门户"
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
