import "./globals.css";

import type { Metadata } from "next";

import { Providers } from "@/components/features/providers";

export const metadata: Metadata = {
  title: "CRM + AI Cockpit",
  description: "Music artist business cockpit"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
