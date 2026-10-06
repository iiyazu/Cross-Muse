import { forwardRef, type ButtonHTMLAttributes } from "react";

import { cx } from "./cx";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "attn";
type Size = "sm" | "md";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-inverse text-on-inverse hover:opacity-90",
  secondary: "bg-canvas text-fg border border-line-strong hover:bg-hover",
  ghost: "text-fg-2 hover:bg-hover hover:text-fg",
  danger: "bg-fail-solid text-white hover:opacity-90",
  attn: "bg-attn-solid text-[oklch(0.25_0.05_70)] hover:opacity-90"
};

const SIZES: Record<Size, string> = {
  sm: "h-7 px-2.5 text-ui gap-1.5",
  md: "h-8 px-3 text-sm gap-2"
};

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: Size;
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", className, type = "button", ...props },
  ref
) {
  return (
    <button
      className={cx(
        "inline-flex shrink-0 items-center justify-center rounded-md font-medium whitespace-nowrap",
        "transition-[background-color,opacity,color] duration-150 select-none",
        "disabled:pointer-events-none disabled:opacity-45",
        VARIANTS[variant],
        SIZES[size],
        className
      )}
      ref={ref}
      type={type}
      {...props}
    />
  );
});

export type IconButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  /** Required: icon-only buttons need an accessible name. */
  label: string;
  size?: Size;
  active?: boolean;
};

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { label, size = "md", active = false, className, type = "button", ...props },
  ref
) {
  return (
    <button
      aria-label={label}
      className={cx(
        "inline-flex shrink-0 items-center justify-center rounded-md text-fg-3",
        "transition-colors duration-150 hover:bg-hover hover:text-fg",
        "disabled:pointer-events-none disabled:opacity-45",
        size === "sm" ? "size-7" : "size-8",
        active && "bg-selected text-fg",
        className
      )}
      ref={ref}
      title={label}
      type={type}
      {...props}
    />
  );
});
