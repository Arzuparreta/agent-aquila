"use client";

import { ChatReferenceProvider } from "@/components/features/chat/reference-context";
import { AuthProvider } from "@/lib/auth";
import { LanguageProvider } from "@/lib/i18n";

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <LanguageProvider>
      <AuthProvider>
        <ChatReferenceProvider>{children}</ChatReferenceProvider>
      </AuthProvider>
    </LanguageProvider>
  );
}
