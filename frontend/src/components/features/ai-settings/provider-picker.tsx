"use client";

import { Combobox, ComboboxOption } from "@/components/ui/combobox";
import { AIProvider } from "@/types/api";

type ProviderPickerProps = {
  providers: AIProvider[];
  value: string;
  onChange: (providerId: string) => void;
  disabled?: boolean;
};

export function ProviderPicker({ providers, value, onChange, disabled }: ProviderPickerProps) {
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
      placeholder="Choose a provider..."
      disabled={disabled}
      ariaLabel="AI provider"
    />
  );
}
