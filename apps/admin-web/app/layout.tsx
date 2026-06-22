import type { ReactNode } from "react";

import "./globals.css";

export const metadata = {
  title: "GENO 内部项目中心",
  description: "澳大利亚 GEO 项目内部配置、启动和审计控制台"
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
