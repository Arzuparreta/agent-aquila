"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

export type ComboboxOption<T = string> = {
  value: T;
  label: string;
  description?: string;
  badge?: string;
  disabled?: boolean;
};

type ComboboxProps<T extends string> = {
  value: T | "";
  onChange: (value: T) => void;
  options: ComboboxOption<T>[];
  placeholder?: string;
  emptyMessage?: string;
  disabled?: boolean;
  allowCustom?: boolean;
  id?: string;
  ariaLabel?: string;
  ariaInvalid?: boolean;
  ariaDescribedBy?: string;
  className?: string;
  name?: string;
  renderOption?: (option: ComboboxOption<T>) => React.ReactNode;
};

const LIST_ID_PREFIX = "combobox-listbox-";

export function Combobox<T extends string>({
  value,
  onChange,
  options,
  placeholder = "Select...",
  emptyMessage = "No matches",
  disabled,
  allowCustom = false,
  id,
  ariaLabel,
  ariaInvalid,
  ariaDescribedBy,
  className,
  name,
  renderOption
}: ComboboxProps<T>) {
  const inputRef = React.useRef<HTMLInputElement>(null);
  const listRef = React.useRef<HTMLUListElement>(null);
  const reactId = React.useId();
  const listboxId = `${LIST_ID_PREFIX}${reactId}`;

  const selectedOption = React.useMemo(
    () => options.find((option) => option.value === value) ?? null,
    [options, value]
  );

  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState<string>(selectedOption?.label ?? (allowCustom ? value : ""));
  const [highlight, setHighlight] = React.useState(0);

  // Keep the displayed text in sync when the selected value changes externally.
  React.useEffect(() => {
    if (!open) {
      setQuery(selectedOption?.label ?? (allowCustom ? value : ""));
    }
  }, [allowCustom, open, selectedOption, value]);

  const filtered = React.useMemo(() => {
    if (!open) return options;
    const trimmed = query.trim().toLowerCase();
    if (!trimmed || trimmed === (selectedOption?.label ?? "").toLowerCase()) {
      return options;
    }
    // Value was typed or defaulted in from outside the option list (e.g. a
    // stale registry default). Until the user edits the field, show every
    // option instead of filtering them out with a query that matches nothing.
    if (
      allowCustom &&
      !selectedOption &&
      value &&
      query.trim() === String(value).trim()
    ) {
      return options;
    }
    return options.filter((option) => {
      const haystack = `${option.label} ${option.description ?? ""} ${option.value}`.toLowerCase();
      return haystack.includes(trimmed);
    });
  }, [allowCustom, open, options, query, selectedOption, value]);

  React.useEffect(() => {
    if (!open) return;
    if (highlight >= filtered.length) {
      setHighlight(filtered.length > 0 ? filtered.length - 1 : 0);
    }
  }, [filtered.length, highlight, open]);

  const commit = React.useCallback(
    (next: T) => {
      onChange(next);
      setOpen(false);
    },
    [onChange]
  );

  const commitCustom = React.useCallback(
    (text: string) => {
      const trimmed = text.trim();
      if (!trimmed) return;
      onChange(trimmed as T);
      setOpen(false);
    },
    [onChange]
  );

  const handleSelectByIndex = (index: number) => {
    const option = filtered[index];
    if (option && !option.disabled) commit(option.value);
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (disabled) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setOpen(true);
      setHighlight((current) => Math.min(current + 1, Math.max(filtered.length - 1, 0)));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setOpen(true);
      setHighlight((current) => Math.max(current - 1, 0));
    } else if (event.key === "Enter") {
      if (open) {
        event.preventDefault();
        if (filtered[highlight]) {
          handleSelectByIndex(highlight);
        } else if (allowCustom) {
          commitCustom(query);
        }
      } else if (allowCustom) {
        event.preventDefault();
        commitCustom(query);
      }
    } else if (event.key === "Escape") {
      event.preventDefault();
      setOpen(false);
      setQuery(selectedOption?.label ?? (allowCustom ? value : ""));
      inputRef.current?.blur();
    } else if (event.key === "Tab") {
      setOpen(false);
    }
  };

  const onBlur = (event: React.FocusEvent<HTMLDivElement>) => {
    // Keep the popover open when focus moves into the list (mouse click).
    if (event.currentTarget.contains(event.relatedTarget as Node | null)) {
      return;
    }
    setOpen(false);
    if (allowCustom && !selectedOption) {
      commitCustom(query);
    } else {
      setQuery(selectedOption?.label ?? (allowCustom ? value : ""));
    }
  };

  return (
    <div className={cn("relative", className)} onBlur={onBlur}>
      <input
        ref={inputRef}
        role="combobox"
        type="text"
        name={name}
        id={id}
        aria-label={ariaLabel}
        aria-expanded={open}
        aria-controls={listboxId}
        aria-autocomplete="list"
        aria-activedescendant={open && filtered[highlight] ? `${listboxId}-opt-${highlight}` : undefined}
        aria-invalid={ariaInvalid || undefined}
        aria-describedby={ariaDescribedBy}
        autoComplete="off"
        value={query}
        disabled={disabled}
        placeholder={placeholder}
        onChange={(event) => {
          setQuery(event.target.value);
          setOpen(true);
          setHighlight(0);
        }}
        onFocus={() => setOpen(true)}
        onClick={() => setOpen(true)}
        onKeyDown={onKeyDown}
        className={cn(
          "w-full rounded border border-border bg-surface-inset px-3 py-2 pr-8 text-base leading-normal text-fg md:text-sm",
          "focus:border-primary focus:outline-none focus:ring-1 focus:ring-ring",
          disabled && "cursor-not-allowed bg-surface-muted text-fg-subtle"
        )}
      />
      <button
        type="button"
        aria-hidden="true"
        tabIndex={-1}
        onMouseDown={(event) => {
          event.preventDefault();
          if (!disabled) {
            setOpen((current) => !current);
            inputRef.current?.focus();
          }
        }}
        className="absolute inset-y-0 right-0 flex w-8 items-center justify-center text-fg-subtle hover:text-fg-muted"
      >
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
          <path d="M3 4.5L6 7.5L9 4.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open ? (
        <ul
          ref={listRef}
          role="listbox"
          id={listboxId}
          className="absolute z-20 mt-1 max-h-64 w-full overflow-auto rounded-md border border-border bg-surface-elevated py-1 text-sm text-fg shadow-lg"
        >
          {filtered.length === 0 ? (
            <li className="px-3 py-2 text-fg-subtle">
              {allowCustom && query.trim() ? (
                <span>
                  Press Enter to use <strong>{query.trim()}</strong>
                </span>
              ) : (
                emptyMessage
              )}
            </li>
          ) : (
            filtered.map((option, index) => {
              const active = index === highlight;
              const selected = option.value === value;
              return (
                <li
                  key={option.value}
                  id={`${listboxId}-opt-${index}`}
                  role="option"
                  aria-selected={selected}
                  aria-disabled={option.disabled || undefined}
                  onMouseDown={(event) => {
                    event.preventDefault();
                    if (!option.disabled) commit(option.value);
                  }}
                  onMouseEnter={() => setHighlight(index)}
                  className={cn(
                    "cursor-pointer px-3 py-2",
                    option.disabled && "cursor-not-allowed text-fg-subtle",
                    !option.disabled && active && "bg-surface-muted",
                    !option.disabled && !active && "hover:bg-interactive-hover"
                  )}
                >
                  {renderOption ? (
                    renderOption(option)
                  ) : (
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className={cn("truncate font-medium", selected && "text-fg")}>{option.label}</div>
                        {option.description ? (
                          <div className="truncate text-xs text-fg-subtle">{option.description}</div>
                        ) : null}
                      </div>
                      {option.badge ? (
                        <span className="shrink-0 rounded bg-surface-muted px-2 py-0.5 text-xs text-fg-muted">
                          {option.badge}
                        </span>
                      ) : null}
                    </div>
                  )}
                </li>
              );
            })
          )}
        </ul>
      ) : null}
    </div>
  );
}
