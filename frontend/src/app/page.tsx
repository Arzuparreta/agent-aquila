"use client";

import { ProtectedPage } from "@/components/features/protected-page";
import { ChatHome } from "@/components/features/chat/chat-home";

export default function HomePage() {
  return (
    <ProtectedPage>
      <ChatHome />
    </ProtectedPage>
  );
}
