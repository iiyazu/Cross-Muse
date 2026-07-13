import type { Metadata } from "next";

import { ChatWorkspace } from "@/components/chat-workspace";
import "./globals.css";

export const metadata: Metadata = {
  title: "xmuse Workroom",
  description: "xmuse 本地工作群聊",
  icons: {
    icon: "/icon.svg"
  }
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN" data-theme="dark">
      <body>
        <ChatWorkspace />
        {children}
      </body>
    </html>
  );
}
