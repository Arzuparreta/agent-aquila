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

/*
 * The width/initial-scale/etc. live in the manual <meta> in <head> below
 * because we also need `interactive-widget=resizes-content`, which the
 * typed Viewport API doesn't expose. Keeping only `themeColor` here so
 * Next.js still emits the theme-color meta but does NOT emit a
 * conflicting viewport meta of its own.
 */
export const viewport: Viewport = {
  themeColor: "#09090b"
};

const themeInitScript = `(function(){try{var k='manager-theme';var v=localStorage.getItem(k);var t=v==='light'||v==='dark'?v:'dark';document.documentElement.setAttribute('data-theme',t);}catch(e){document.documentElement.setAttribute('data-theme','dark');}})();`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es" suppressHydrationWarning data-theme="dark">
      <head>
        {/*
         * `interactive-widget=resizes-content` makes iOS Safari (16.4+)
         * and Android Chrome shrink the layout viewport when the
         * on-screen keyboard appears. Combined with the .app-shell
         * `position: fixed; inset: 0` pattern, this keeps the chat
         * composer pinned right above the keyboard instead of being
         * covered by it. Next.js's typed Viewport API does not expose
         * this key yet, so we render the meta tag manually.
         */}
        <meta
          name="viewport"
          content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover, interactive-widget=resizes-content"
        />
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
