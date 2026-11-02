// 2.4.0 (#473): Vite's "?raw" imports (the bundled user guide) are plain strings.
declare module "*?raw" {
  const text: string;
  export default text;
}
