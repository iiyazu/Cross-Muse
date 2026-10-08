import type { Metadata, Viewport } from "next";
import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";

import { Workroom } from "@/components/shell/workroom";
import { THEME_BOOT_SCRIPT } from "@/components/shell/theme";
import "./globals.css";

export const metadata: Metadata = {
  title: "xmuse",
  description: "xmuse 本地多 Agent 工作室",
  icons: {
    icon: "/icon.svg"
  }
};

export const viewport: Viewport = {
  colorScheme: "light dark"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      className={`${GeistSans.variable} ${GeistMono.variable}`}
      lang="zh-CN"
      suppressHydrationWarning
    >
      <head>
        {/* Resolves the stored theme before first paint; a fixed string, never user data. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT_SCRIPT }} />
      </head>
      <body>
        <Workroom />
        {children}
      </body>
    </html>
  );
}
