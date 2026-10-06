"use client";

import { AlertDialog as AlertPrimitive, Dialog as DialogPrimitive } from "radix-ui";
import { X } from "lucide-react";
import type { ReactNode } from "react";

import { IconButton } from "./button";
import { cx } from "./cx";

const SCRIM = "fixed inset-0 z-40 bg-[oklch(0.1_0.01_265/0.45)]";

/**
 * Side sheet for progressive panels on narrow windows (room list, work panel). Radix owns
 * the focus trap, Escape and focus return.
 */
export function Sheet({
  open,
  onOpenChange,
  side = "right",
  title,
  description,
  children,
  widthClass = "w-[min(100vw,30rem)]"
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  side?: "left" | "right";
  title: string;
  description?: string;
  children: ReactNode;
  widthClass?: string;
}) {
  return (
    <DialogPrimitive.Root onOpenChange={onOpenChange} open={open}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className={SCRIM} />
        <DialogPrimitive.Content
          className={cx(
            "fixed inset-y-0 z-50 flex flex-col bg-canvas shadow-overlay outline-none",
            side === "right" ? "right-0" : "left-0",
            widthClass
          )}
        >
          <DialogPrimitive.Title className="sr-only">{title}</DialogPrimitive.Title>
          <DialogPrimitive.Description className="sr-only">{description ?? title}</DialogPrimitive.Description>
          {children}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

/** Centered dialog with a visible title row and a close button. */
export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  widthClass = "w-[min(calc(100vw-2rem),36rem)]"
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  widthClass?: string;
}) {
  return (
    <DialogPrimitive.Root onOpenChange={onOpenChange} open={open}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className={SCRIM} />
        <DialogPrimitive.Content
          className={cx(
            "fixed top-1/2 left-1/2 z-50 flex max-h-[calc(100dvh-2rem)] -translate-x-1/2 -translate-y-1/2 flex-col",
            "rounded-lg bg-overlay shadow-overlay outline-none",
            widthClass
          )}
        >
          <div className="flex items-start gap-3 border-b border-line px-5 py-4">
            <div className="min-w-0 flex-1">
              <DialogPrimitive.Title className="m-0 text-base font-semibold text-fg">{title}</DialogPrimitive.Title>
              {description ? (
                <DialogPrimitive.Description className="m-0 mt-1 text-ui text-fg-3">{description}</DialogPrimitive.Description>
              ) : (
                <DialogPrimitive.Description className="sr-only">{title}</DialogPrimitive.Description>
              )}
            </div>
            <DialogPrimitive.Close asChild>
              <IconButton label="关闭" size="sm">
                <X className="size-4" />
              </IconButton>
            </DialogPrimitive.Close>
          </div>
          <div className="scrollbar-quiet min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
          {footer ? <div className="flex justify-end gap-2 border-t border-line px-5 py-3">{footer}</div> : null}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

/** Confirmation for irreversible or disruptive operator actions (role="alertdialog"). */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  cancelLabel = "返回",
  pending = false,
  tone = "danger",
  onConfirm
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  pending?: boolean;
  tone?: "danger" | "primary";
  onConfirm: () => void;
}) {
  return (
    <AlertPrimitive.Root onOpenChange={(next) => { if (!pending) onOpenChange(next); }} open={open}>
      <AlertPrimitive.Portal>
        <AlertPrimitive.Overlay className={SCRIM} />
        <AlertPrimitive.Content
          className={cx(
            "fixed top-1/2 left-1/2 z-50 w-[min(calc(100vw-2rem),26rem)] -translate-x-1/2 -translate-y-1/2",
            "rounded-lg bg-overlay p-5 shadow-overlay outline-none"
          )}
        >
          <AlertPrimitive.Title className="m-0 text-base font-semibold text-fg">{title}</AlertPrimitive.Title>
          <AlertPrimitive.Description asChild>
            <div className="mt-2 text-ui text-fg-2">{description}</div>
          </AlertPrimitive.Description>
          <div className="mt-5 flex justify-end gap-2">
            <AlertPrimitive.Cancel
              className="inline-flex h-8 items-center rounded-md border border-line-strong px-3 text-sm font-medium text-fg hover:bg-hover disabled:opacity-45"
              disabled={pending}
            >
              {cancelLabel}
            </AlertPrimitive.Cancel>
            <button
              className={cx(
                "inline-flex h-8 items-center rounded-md px-3 text-sm font-medium disabled:opacity-45",
                tone === "danger" ? "bg-fail-solid text-white hover:opacity-90" : "bg-inverse text-on-inverse hover:opacity-90"
              )}
              disabled={pending}
              onClick={onConfirm}
              type="button"
            >
              {confirmLabel}
            </button>
          </div>
        </AlertPrimitive.Content>
      </AlertPrimitive.Portal>
    </AlertPrimitive.Root>
  );
}
