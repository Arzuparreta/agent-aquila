"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Lightweight popover menu — vanilla React + tailwind, no Radix dependency.
 *
 * Usage:
 *
 *   <DropdownMenu trigger={<button>...</button>}>
 *     <DropdownMenuItem onSelect={...}>Renombrar</DropdownMenuItem>
 *     <DropdownMenuSeparator />
 *     <DropdownMenuItem destructive onSelect={...}>Eliminar</DropdownMenuItem>
 *   </DropdownMenu>
 *
 * Behavior:
 * - Click trigger to toggle. Click outside or press Escape to close.
 * - Selecting any item closes the menu (callers can prevent that with
 *   ``onSelect={(close) => { ... }}``-style if needed; the shipped item
 *   API just calls ``onSelect()`` and then closes).
 * - The menu is anchored to the trigger via a wrapping ``relative`` span
 *   and absolute positioning. ``align="end"`` (default) right-aligns it.
 * - ``onOpenChange`` lets parents react (e.g. show/hide a hover-only
 *   trigger while the menu is open).
 */

type Align = "start" | "end";

type DropdownMenuContextValue = {
  close: () => void;
};

const DropdownMenuContext = React.createContext<DropdownMenuContextValue | null>(null);

export function DropdownMenu({
  trigger,
  children,
  align = "end",
  className,
  menuClassName,
  open: controlledOpen,
  onOpenChange,
  stopPropagation = true,
}: {
  trigger: React.ReactNode;
  children: React.ReactNode;
  align?: Align;
  className?: string;
  menuClassName?: string;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  stopPropagation?: boolean;
}) {
  const [uncontrolledOpen, setUncontrolledOpen] = React.useState(false);
  const isControlled = controlledOpen !== undefined;
  const open = isControlled ? controlledOpen : uncontrolledOpen;

  const setOpen = React.useCallback(
    (next: boolean) => {
      if (!isControlled) setUncontrolledOpen(next);
      onOpenChange?.(next);
    },
    [isControlled, onOpenChange]
  );

  const close = React.useCallback(() => setOpen(false), [setOpen]);

  const wrapRef = React.useRef<HTMLSpanElement | null>(null);

  const onTriggerClick = React.useCallback(
    (e: React.MouseEvent) => {
      if (stopPropagation) e.stopPropagation();
      setOpen(!open);
    },
    [open, setOpen, stopPropagation]
  );

  React.useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (!wrapRef.current) return;
      if (e.target instanceof Node && wrapRef.current.contains(e.target)) return;
      close();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, close]);

  // Merge toggle into the trigger's click handler. Wrapping the trigger in a parent
  // ``<span onClick>`` breaks when the trigger calls ``stopPropagation()`` (used on
  // row menus so the row's own click does not fire): the event never reaches the
  // wrapper, so the menu never opens.
  const triggerNode = React.isValidElement(trigger)
    ? React.cloneElement(
        trigger as React.ReactElement<{ onClick?: React.MouseEventHandler<HTMLElement> }>,
        {
          onClick: (e: React.MouseEvent<HTMLElement>) => {
            (trigger as React.ReactElement<{ onClick?: React.MouseEventHandler<HTMLElement> }>).props.onClick?.(
              e
            );
            onTriggerClick(e as React.MouseEvent);
          },
        }
      )
    : (
        <span className="inline-flex cursor-pointer" role="presentation" onClick={onTriggerClick}>
          {trigger}
        </span>
      );

  return (
    <span ref={wrapRef} className={cn("relative inline-flex", className)}>
      {triggerNode}
      {open ? (
        <DropdownMenuContext.Provider value={{ close }}>
          <div
            role="menu"
            onClick={(e) => {
              if (stopPropagation) e.stopPropagation();
            }}
            className={cn(
              "absolute top-full z-40 mt-1 min-w-[12rem] overflow-hidden rounded-lg border border-border bg-surface-elevated py-1 text-sm text-fg shadow-xl",
              align === "end" ? "right-0" : "left-0",
              menuClassName
            )}
          >
            {children}
          </div>
        </DropdownMenuContext.Provider>
      ) : null}
    </span>
  );
}

export function DropdownMenuItem({
  children,
  onSelect,
  destructive = false,
  disabled = false,
  className,
}: {
  children: React.ReactNode;
  onSelect: () => void;
  destructive?: boolean;
  disabled?: boolean;
  className?: string;
}) {
  const ctx = React.useContext(DropdownMenuContext);
  return (
    <button
      type="button"
      role="menuitem"
      disabled={disabled}
      onClick={(e) => {
        e.stopPropagation();
        if (disabled) return;
        onSelect();
        ctx?.close();
      }}
      className={cn(
        "block w-full px-3 py-2 text-left transition hover:bg-interactive-hover disabled:cursor-not-allowed disabled:opacity-50",
        destructive ? "text-rose-600 hover:bg-rose-500/10 hover:text-rose-700" : "",
        className
      )}
    >
      {children}
    </button>
  );
}

export function DropdownMenuSeparator() {
  return <div className="my-1 h-px bg-border-subtle" role="separator" />;
}

export function DropdownMenuLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="px-3 py-1 text-[10px] font-semibold uppercase tracking-wide text-fg-subtle">
      {children}
    </div>
  );
}
