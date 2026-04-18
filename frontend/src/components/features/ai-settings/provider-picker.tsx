"use client";

import { Combobox, ComboboxOption } from "@/components/ui/combobox";
import { useTranslation } from "@/lib/i18n";
import { AIProvider } from "@/types/api";

type ProviderPickerProps = {
  providers: AIProvider[];
  value: string;
  onChange: (providerId: string) => void;
  disabled?: boolean;
};

export function ProviderPicker({ providers, value, onChange, disabled }: ProviderPickerProps) {
  const { t } = useTranslation();
  const options: ComboboxOption<string>[] = providers.map((provider) => ({
    value: provider.id,
    label: provider.label,
    description: provider.description
  }));

  return (
    <Combobox
      value={value}
      onChange={onChange}
      options={options}
      placeholder={t("settings.providerPlaceholder")}
      disabled={disabled}
      ariaLabel={t("settings.providerAriaLabel")}
    />
  );
}
