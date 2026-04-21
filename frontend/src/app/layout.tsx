import "./globals.css";

import type { Metadata, Viewport } from "next";

import { Providers } from "@/components/features/providers";

export const metadata: Metadata = {
  title: "Agent Aquila",
  description: "Your self-hosted operations assistant in one conversation.",
  manifest: "/manifest.webmanifest",
  applicationName: "Agent Aquila",
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "Agent Aquila"
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

const themeInitScript = `(function(){try{var kn='agent-aquila-theme';var ko='manager-theme';var v=localStorage.getItem(kn)||localStorage.getItem(ko);if((v==='light'||v==='dark')&&!localStorage.getItem(kn)){localStorage.setItem(kn,v);}var t=v==='light'||v==='dark'?v:'dark';document.documentElement.setAttribute('data-theme',t);}catch(e){document.documentElement.setAttribute('data-theme','dark');}})();`;

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
