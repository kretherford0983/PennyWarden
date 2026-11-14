// 2.4.0 (#473): Vite's "?raw" imports (the bundled user guide) are plain strings.
declare module "*?raw" {
  const text: string;
  export default text;
}

// 2.4.0 (#488): the guide's pages and pictures are bundled with Vite's import.meta.glob (helpDocs.ts)
interface ImportMeta {
  glob(pattern: string, options: { query: string; import: string; eager: true }): Record<string, unknown>;
}
