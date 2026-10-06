"use client";

import { Sheet } from "@/components/ui/overlay";

export function SystemSheet({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  return (
    <Sheet onOpenChange={onOpenChange} open={open} title="系统">
      <div className="p-4 text-ui text-fg-3">系统</div>
    </Sheet>
  );
}
