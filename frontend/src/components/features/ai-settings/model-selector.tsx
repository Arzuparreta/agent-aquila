"use client";

import { Combobox, ComboboxOption } from "@/components/ui/combobox";
import { cn } from "@/lib/utils";
import { ModelCapability, ModelInfo } from "@/types/api";

type ModelSelectorProps = {
  id?: string;
  label: string;
  required?: boolean;
  value: string;
  onChange: (value: string) => void;
  models: ModelInfo[];
  loading?: boolean;
  capability?: ModelCapability;
  disabledReason?: string | null;
  helpText?: string;
  emptyHint?: string;
  placeholder?: string;
};

/**
 * Searchable combobox of model ids returned by the backend's list-models
 * endpoint. Falls back to free-text entry so users can always type in a
 * model the server didn't advertise (e.g. a private Ollama model they
 * haven't pulled yet).
 */
export function ModelSelector({
  id,
  label,
  required,
  value,
  onChange,
  models,
  loading,
  capability,
  disabledReason,
  helpText,
  emptyHint,
  placeholder
}: ModelSelectorProps) {
  const reactId = id ?? `model-${label.replace(/\s+/g, "-").toLowerCase()}`;
  const helpId = helpText ? `${reactId}-help` : undefined;

  const options: ComboboxOption<string>[] = models.map((model) => ({
    value: model.id,
    label: model.label,
    description: model.id !== model.label ? model.id : undefined,
    badge: capability || model.capability === "unknown" ? undefined : model.capability
  }));

  const placeholderText = loading
    ? "Loading models..."
    : disabledReason
      ? disabledReason
      : models.length === 0
        ? emptyHint || "Test the connection to load models"
        : placeholder || "Select or type a model";

  return (
    <div className="grid gap-1">
      <label htmlFor={reactId} className="text-sm font-medium text-slate-800">
        {label}
        {required ? <span className="ml-1 text-red-600">*</span> : null}
      </label>
      <Combobox
        id={reactId}
        value={value}
        onChange={onChange}
        options={options}
        placeholder={placeholderText}
        disabled={Boolean(disabledReason) || loading}
        allowCustom
        ariaDescribedBy={helpId}
      />
      {helpText ? (
        <p id={helpId} className={cn("text-xs text-slate-500")}>
          {helpText}
        </p>
      ) : null}
    </div>
  );
}
