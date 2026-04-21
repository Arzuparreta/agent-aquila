"use client";

import { ChatReferenceProvider } from "@/components/features/chat/reference-context";
import { TelemetryGlobalHandlers } from "@/lib/telemetry/global-handlers";
import { AuthProvider } from "@/lib/auth";
import { LanguageProvider } from "@/lib/i18n";
import { ThemeProvider } from "@/lib/theme";

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider>
      <LanguageProvider>
        <AuthProvider>
          <TelemetryGlobalHandlers />
          <ChatReferenceProvider>{children}</ChatReferenceProvider>
        </AuthProvider>
      </LanguageProvider>
    </ThemeProvider>
  );
}
