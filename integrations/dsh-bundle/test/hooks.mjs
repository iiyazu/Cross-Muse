// Resolves the @deepseek-ai/* packages that dsh normally provides to local stubs.
const MAP = {
  '@deepseek-ai/dsh-commands/brand': './stubs/brand.mjs',
  '@deepseek-ai/dsh-llm': './stubs/llm.mjs',
  '@deepseek-ai/dsh-tools': './stubs/tools.mjs',
}
export async function resolve(specifier, context, next) {
  if (MAP[specifier]) return { url: new URL(MAP[specifier], import.meta.url).href, shortCircuit: true }
  return next(specifier, context)
}
