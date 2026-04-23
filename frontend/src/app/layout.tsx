import "./globals.css";

import type { Metadata, Viewport } from "next";

import { Providers } from "@/components/features/providers";

export const metadata: Metadata = {
  title: "Agent Aquila",
  description: "Your self-hosted operations assistant in one conversation.",
  manifest: "/manifest.webmanifest",
  applicationName: "Agent Aquila",
  formatDetection: {
    telephone: false,
    email: false,
    address: false,
  },
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "Agent Aquila",
  },
  icons: {
    icon: "/icons/icon.svg",
    apple: [
      {
        url: "/icons/apple-touch-icon.png",
        sizes: "180x180",
        type: "image/png",
      },
    ],
  },
};

/** Single viewport meta — duplicates break iOS (zoom lock + standalone hints). */
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  viewportFit: "cover",
  interactiveWidget: "resizes-content",
  themeColor: "#09090b",
};

const themeInitScript = `(function(){try{var kn='agent-aquila-theme';var ko='manager-theme';var v=localStorage.getItem(kn)||localStorage.getItem(ko);if((v==='light'||v==='dark')&&!localStorage.getItem(kn)){localStorage.setItem(kn,v);}var t=v==='light'||v==='dark'?v:'dark';document.documentElement.setAttribute('data-theme',t);}catch(e){document.documentElement.setAttribute('data-theme','dark');}})();`;

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
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
