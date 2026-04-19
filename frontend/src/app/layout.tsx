import "./globals.css";

import type { Metadata, Viewport } from "next";

import { Providers } from "@/components/features/providers";

export const metadata: Metadata = {
  title: "Mánager",
  description: "Tu mánager personal en una sola conversación.",
  manifest: "/manifest.webmanifest",
  applicationName: "Mánager",
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "Mánager"
  },
  icons: {
    icon: "/icons/icon.svg",
    apple: "/icons/icon.svg"
  }
};

export const viewport: Viewport = {
  themeColor: "#09090b",
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  viewportFit: "cover"
};

const themeInitScript = `(function(){try{var k='manager-theme';var v=localStorage.getItem(k);var t=v==='light'||v==='dark'?v:'dark';document.documentElement.setAttribute('data-theme',t);}catch(e){document.documentElement.setAttribute('data-theme','dark');}})();`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es" suppressHydrationWarning data-theme="dark">
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
