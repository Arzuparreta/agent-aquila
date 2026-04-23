"use client";

import Link from "next/link";
import { ProtectedPage } from "@/components/features/protected-page";
import {
  SETTINGS_GROUPS,
  SETTINGS_SECTIONS,
  SettingsSectionIcon,
  type SettingsSection
} from "@/components/features/settings/settings-sections";
import { SettingsLayout } from "@/components/features/settings/settings-shell";
import { Card } from "@/components/ui/card";
import { useTranslation } from "@/lib/i18n";

/**
 * Settings hub with grouped sections and dedicated subpages.
 */
export default function SettingsPage() {
  const { t } = useTranslation();

  return (
    <ProtectedPage>
      <SettingsLayout
        title={t("settings.hub.title")}
        intro={t("settings.hub.intro")}
        backHref="/"
        backLabel={t("settings.technical.backToChat")}
      >
        <div className="space-y-4">
          {SETTINGS_GROUPS.map((group) => {
            const sections = SETTINGS_SECTIONS.filter((section) => section.group === group.id);
            return (
              <section key={group.id} aria-label={t(group.titleKey)}>
                <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-fg-muted">{t(group.titleKey)}</h2>
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {sections.map((section) => (
                    <SettingsHubCard key={section.id} section={section} />
                  ))}
                </div>
              </section>
            );
          })}
        </div>
      </SettingsLayout>
    </ProtectedPage>
  );
}

function SettingsHubCard({ section }: { section: SettingsSection }) {
  const { t } = useTranslation();

  return (
    <Link href={section.href} className="rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      <Card className="h-full transition-colors hover:border-primary hover:bg-surface-muted">
        <div className="mb-3 inline-flex rounded-md border border-border bg-surface-base p-2 text-fg">
          <SettingsSectionIcon sectionId={section.id} />
        </div>
        <h3 className="text-sm font-semibold text-fg">{t(section.titleKey)}</h3>
        <p className="mt-1 text-sm text-fg-muted">{t(section.descriptionKey)}</p>
      </Card>
    </Link>
  );
}
