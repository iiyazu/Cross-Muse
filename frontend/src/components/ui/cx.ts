/** Joins class names, dropping falsy entries. Variants are designed not to conflict. */
export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}
