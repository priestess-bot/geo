import type { ReactNode } from "react";

import "./globals.css";

export const metadata = {
  title: "GENO AU Evidence Platform",
  description: "Evidence-first AI Search Visibility MVP for Australia"
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en-AU">
      <body>{children}</body>
    </html>
  );
}
