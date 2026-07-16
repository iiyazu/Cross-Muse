"use client";

import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { Command, Search, X } from "lucide-react";

export type CommandPaletteAction = {
  id: string;
  label: string;
  detail: string;
  run: () => void;
};

export function CommandPalette({ actions }: { actions: CommandPaletteAction[] }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const wasOpenRef = useRef(false);

  useEffect(() => {
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        if (open) closePalette();
        else setOpen(true);
      } else if (event.key === "Escape") {
        closePalette();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open]);

  useEffect(() => {
    if (open) {
      wasOpenRef.current = true;
      requestAnimationFrame(() => inputRef.current?.focus());
    } else if (wasOpenRef.current) requestAnimationFrame(() => triggerRef.current?.focus());
  }, [open]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return actions.filter((action) =>
      !needle || `${action.label} ${action.detail}`.toLocaleLowerCase().includes(needle)
    ).slice(0, 12);
  }, [actions, query]);

  function closePalette() {
    setOpen(false);
    setQuery("");
    setActiveIndex(0);
  }

  function run(index: number) {
    const action = filtered[index];
    if (!action) return;
    closePalette();
    action.run();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key === "ArrowDown" && filtered.length) {
      event.preventDefault();
      setActiveIndex((index) => (index + 1) % filtered.length);
    } else if (event.key === "ArrowUp" && filtered.length) {
      event.preventDefault();
      setActiveIndex((index) => (index - 1 + filtered.length) % filtered.length);
    } else if (event.key === "Enter" && document.activeElement === inputRef.current) {
      event.preventDefault();
      run(activeIndex);
    } else if (event.key === "Tab") {
      const controls = [...event.currentTarget.querySelectorAll<HTMLElement>("input, button:not(:disabled)")];
      const first = controls[0];
      const last = controls.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    }
  }

  if (!open) return (
    <button aria-label="打开导航面板" className="command-palette-trigger" onClick={() => setOpen(true)} ref={triggerRef} type="button">
      <Command size={14} /><span>⌘K</span>
    </button>
  );

  return (
    <div className="room-dialog-layer command-palette-layer">
      <button aria-label="关闭导航面板" className="room-dialog-scrim" onClick={closePalette} type="button" />
      <section aria-label="导航面板" aria-modal="true" className="command-palette" onKeyDown={handleKeyDown} role="dialog">
        <header><Search aria-hidden="true" size={17} /><input aria-label="搜索命令" onChange={(event) => { setQuery(event.target.value); setActiveIndex(0); }} placeholder="切换 Room、选择 Agent 或打开工作台…" ref={inputRef} value={query} /><button aria-label="关闭" className="room-icon-button" onClick={closePalette} type="button"><X size={17} /></button></header>
        <div aria-activedescendant={filtered[activeIndex] ? `command-${filtered[activeIndex].id}` : undefined} className="command-palette-list" role="listbox">
          {filtered.map((action, index) => (
            <button aria-selected={index === activeIndex} className={index === activeIndex ? "is-active" : ""} id={`command-${action.id}`} key={action.id} onClick={() => run(index)} role="option" type="button">
              <strong>{action.label}</strong><span>{action.detail}</span>
            </button>
          ))}
          {!filtered.length ? <p>没有匹配的导航动作</p> : null}
        </div>
        <footer>仅导航，不会直接执行 Agent 或 Runtime 动作</footer>
      </section>
    </div>
  );
}
