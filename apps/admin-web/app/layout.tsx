import type { ReactNode } from "react";
import { GEO_UI_VERSION } from "@geo/ui";

import "./globals.css";

export const metadata = {
  title: "GEO 项目管理台",
  description: "GEO 项目内部配置、启动和验收控制台"
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body data-geo-ui={GEO_UI_VERSION}>{children}</body>
    </html>
  );
}
