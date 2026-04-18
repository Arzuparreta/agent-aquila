"use client";

import { Input } from "@/components/ui/input";
import { useTranslation } from "@/lib/i18n";
import { AIProvider, ProviderField } from "@/types/api";

type ProviderFieldsValue = {
  apiKey: string;
  baseUrl: string;
  extras: Record<string, string>;
};

type ProviderFieldsProps = {
  provider: AIProvider;
  value: ProviderFieldsValue;
  storedApiKey: boolean;
  onChange: (next: ProviderFieldsValue) => void;
  idPrefix?: string;
};

/**
 * Renders the dynamic input list for the selected provider.
 *
 * Field `key` maps to three slots:
 *   - "api_key" → the top-level (encrypted) API key
 *   - "base_url" → the top-level base URL override
 *   - anything else → the free-form `extras` JSON bag (string values only)
 */
export function ProviderFields({ provider, value, storedApiKey, onChange, idPrefix = "pf" }: ProviderFieldsProps) {
  const { t } = useTranslation();
  const set = (patch: Partial<ProviderFieldsValue>) => onChange({ ...value, ...patch });

  const renderInput = (field: ProviderField) => {
    const id = `${idPrefix}-${field.key}`;
    const helpId = field.help ? `${id}-help` : undefined;
    const required = field.required;

    if (field.key === "api_key") {
      const placeholder = storedApiKey
        ? t("providerFields.apiKeyMaskedPlaceholder")
        : field.placeholder || "sk-...";
      return (
        <div key={field.key} className="grid gap-1">
          <label htmlFor={id} className="text-sm font-medium text-slate-800">
            {field.label}
            {required && !storedApiKey ? <span className="ml-1 text-red-600">*</span> : null}
          </label>
          <Input
            id={id}
            type="password"
            autoComplete="new-password"
            placeholder={placeholder}
            value={value.apiKey}
            onChange={(event) => set({ apiKey: event.target.value })}
            aria-describedby={helpId}
          />
          {field.help ? (
            <p id={helpId} className="text-xs text-slate-500">
              {field.help}
            </p>
          ) : null}
        </div>
      );
    }

    if (field.key === "base_url") {
      return (
        <div key={field.key} className="grid gap-1">
          <label htmlFor={id} className="text-sm font-medium text-slate-800">
            {field.label}
            {required ? <span className="ml-1 text-red-600">*</span> : null}
          </label>
          <Input
            id={id}
            type="url"
            inputMode="url"
            placeholder={field.placeholder || provider.default_base_url || ""}
            value={value.baseUrl}
            onChange={(event) => set({ baseUrl: event.target.value })}
            aria-describedby={helpId}
          />
          {field.help ? (
            <p id={helpId} className="text-xs text-slate-500">
              {field.help}
            </p>
          ) : null}
        </div>
      );
    }

    const extraValue = value.extras[field.key] ?? "";
    return (
      <div key={field.key} className="grid gap-1">
        <label htmlFor={id} className="text-sm font-medium text-slate-800">
          {field.label}
          {required ? <span className="ml-1 text-red-600">*</span> : null}
        </label>
        <Input
          id={id}
          type={field.type === "url" ? "url" : "text"}
          placeholder={field.placeholder}
          value={extraValue}
          onChange={(event) => set({ extras: { ...value.extras, [field.key]: event.target.value } })}
          aria-describedby={helpId}
        />
        {field.help ? (
          <p id={helpId} className="text-xs text-slate-500">
            {field.help}
          </p>
        ) : null}
      </div>
    );
  };

  return <div className="grid gap-3">{provider.fields.map(renderInput)}</div>;
}

export type { ProviderFieldsValue };
