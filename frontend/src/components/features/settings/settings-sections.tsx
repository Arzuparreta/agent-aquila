import type { ComponentPropsWithoutRef } from "react";
import type { TranslationKey } from "@/lib/i18n";

export type SettingsSectionId =
  | "ai"
  | "agent-runtime"
  | "appearance"
  | "language"
  | "connectors"
  | "telegram"
  | "telemetry"
  | "memory"
  | "skills"
  | "maintenance"
  | "users";

export type SettingsSection = {
  id: SettingsSectionId;
  href: `/settings/${string}`;
  group: "core" | "personalization" | "operations";
  titleKey: TranslationKey;
  descriptionKey: TranslationKey;
};

export const SETTINGS_SECTIONS: SettingsSection[] = [
  {
    id: "ai",
    href: "/settings/ai",
    group: "core",
    titleKey: "settings.hub.section.ai.title",
    descriptionKey: "settings.hub.section.ai.description"
  },
  {
    id: "agent-runtime",
    href: "/settings/agent-runtime",
    group: "core",
    titleKey: "settings.hub.section.runtime.title",
    descriptionKey: "settings.hub.section.runtime.description"
  },
  {
    id: "connectors",
    href: "/settings/connectors",
    group: "core",
    titleKey: "settings.hub.section.connectors.title",
    descriptionKey: "settings.hub.section.connectors.description"
  },
  {
    id: "telegram",
    href: "/settings/telegram",
    group: "core",
    titleKey: "settings.hub.section.telegram.title",
    descriptionKey: "settings.hub.section.telegram.description"
  },
  {
    id: "users",
    href: "/settings/users",
    group: "core",
    titleKey: "settings.hub.section.users.title",
    descriptionKey: "settings.hub.section.users.description"
  },
  {
    id: "appearance",
    href: "/settings/appearance",
    group: "personalization",
    titleKey: "settings.hub.section.appearance.title",
    descriptionKey: "settings.hub.section.appearance.description"
  },
  {
    id: "language",
    href: "/settings/language",
    group: "personalization",
    titleKey: "settings.hub.section.language.title",
    descriptionKey: "settings.hub.section.language.description"
  },
  {
    id: "telemetry",
    href: "/settings/telemetry",
    group: "operations",
    titleKey: "settings.hub.section.telemetry.title",
    descriptionKey: "settings.hub.section.telemetry.description"
  },
  {
    id: "memory",
    href: "/settings/memory",
    group: "operations",
    titleKey: "settings.hub.section.memory.title",
    descriptionKey: "settings.hub.section.memory.description"
  },
  {
    id: "skills",
    href: "/settings/skills",
    group: "operations",
    titleKey: "settings.hub.section.skills.title",
    descriptionKey: "settings.hub.section.skills.description"
  },
  {
    id: "maintenance",
    href: "/settings/maintenance",
    group: "operations",
    titleKey: "settings.hub.section.maintenance.title",
    descriptionKey: "settings.hub.section.maintenance.description"
  }
];

export const SETTINGS_GROUPS: Array<{ id: SettingsSection["group"]; titleKey: TranslationKey }> = [
  { id: "core", titleKey: "settings.hub.group.core" },
  { id: "personalization", titleKey: "settings.hub.group.personalization" },
  { id: "operations", titleKey: "settings.hub.group.operations" }
];

export function SettingsSectionIcon({
  sectionId,
  className,
  ...props
}: {
  sectionId: SettingsSectionId;
} & ComponentPropsWithoutRef<"svg">) {
  const base = {
    className: className ?? "h-5 w-5",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    ...props
  };

  switch (sectionId) {
    case "ai":
      return (
        <svg {...base}>
          <path d="M12 3v4" />
          <path d="M12 17v4" />
          <path d="M3 12h4" />
          <path d="M17 12h4" />
          <circle cx="12" cy="12" r="4" />
        </svg>
      );
    case "agent-runtime":
      return (
        <svg {...base}>
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1 1 0 0 0 .2 1.1l.1.1a1 1 0 1 1-1.4 1.4l-.1-.1a1 1 0 0 0-1.1-.2 1 1 0 0 0-.6.9V19a1 1 0 1 1-2 0v-.1a1 1 0 0 0-.7-1 1 1 0 0 0-1.1.2l-.1.1a1 1 0 1 1-1.4-1.4l.1-.1a1 1 0 0 0 .2-1.1 1 1 0 0 0-.9-.6H9a1 1 0 1 1 0-2h.1a1 1 0 0 0 .9-.6 1 1 0 0 0-.2-1.1l-.1-.1a1 1 0 1 1 1.4-1.4l.1.1a1 1 0 0 0 1.1.2 1 1 0 0 0 .6-.9V5a1 1 0 1 1 2 0v.1a1 1 0 0 0 .6.9 1 1 0 0 0 1.1-.2l.1-.1a1 1 0 1 1 1.4 1.4l-.1.1a1 1 0 0 0-.2 1.1 1 1 0 0 0 .9.6H19a1 1 0 1 1 0 2h-.1a1 1 0 0 0-.9.6Z" />
        </svg>
      );
    case "appearance":
      return (
        <svg {...base}>
          <path d="M12 3v18" />
          <path d="M12 5a7 7 0 1 0 0 14" />
          <path d="M12 5a7 7 0 0 1 0 14" />
        </svg>
      );
    case "language":
      return (
        <svg {...base}>
          <path d="M4 6h16" />
          <path d="M8 6c0 6-2 10-4 12" />
          <path d="M16 6c0 6 2 10 4 12" />
          <path d="M8 12h8" />
        </svg>
      );
    case "connectors":
      return (
        <svg {...base}>
          <path d="M8 12a3 3 0 0 1 3-3h2" />
          <path d="M16 12a3 3 0 0 1-3 3h-2" />
          <path d="M9 9 7 7a3 3 0 1 0-4 4l2 2" />
          <path d="m15 15 2 2a3 3 0 0 0 4-4l-2-2" />
        </svg>
      );
    case "telegram":
      return (
        <svg {...base}>
          <path d="M21 5 3 12l5 2 2 5 4-8 4 2z" />
          <path d="m10 14 1 4 2-2" />
        </svg>
      );
    case "telemetry":
      return (
        <svg {...base}>
          <path d="M4 18h16" />
          <path d="m7 15 3-4 3 2 4-6" />
          <circle cx="7" cy="15" r="1" />
          <circle cx="10" cy="11" r="1" />
          <circle cx="13" cy="13" r="1" />
          <circle cx="17" cy="7" r="1" />
        </svg>
      );
    case "memory":
      return (
        <svg {...base}>
          <path d="M6 8a6 6 0 0 1 12 0v5a6 6 0 0 1-12 0Z" />
          <path d="M9 10h.01" />
          <path d="M12 10h.01" />
          <path d="M15 10h.01" />
          <path d="M10 14h4" />
        </svg>
      );
    case "skills":
      return (
        <svg {...base}>
          <path d="M6 7h12v10H6z" />
          <path d="m9 7 3-3 3 3" />
          <path d="M9 12h6" />
          <path d="M9 15h4" />
        </svg>
      );
    case "maintenance":
      return (
        <svg {...base}>
          <path d="m14 7 3 3-7 7H7v-3z" />
          <path d="m16 5 3 3" />
          <path d="M4 20h16" />
        </svg>
      );
    case "users":
      return (
        <svg {...base}>
          <path d="M16 19a4 4 0 0 0-8 0" />
          <circle cx="12" cy="10" r="3" />
          <path d="M20 8v6" />
          <path d="M17 11h6" />
        </svg>
      );
    default:
      return null;
  }
}
