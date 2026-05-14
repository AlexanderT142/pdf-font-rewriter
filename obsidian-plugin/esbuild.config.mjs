import { builtinModules } from "module";
import esbuild from "esbuild";

const prod = process.argv[2] === "production";

const context = await esbuild.context({
  banner: {
    js: "/* PDF Font Rewriter Obsidian plugin */",
  },
  bundle: true,
  entryPoints: ["src/main.ts"],
  external: [
    "obsidian",
    "electron",
    "@codemirror/autocomplete",
    "@codemirror/collab",
    "@codemirror/commands",
    "@codemirror/language",
    "@codemirror/lint",
    "@codemirror/search",
    "@codemirror/state",
    "@codemirror/view",
    "@lezer/common",
    "@lezer/highlight",
    "@lezer/lr",
    ...builtinModules,
    ...builtinModules.map((moduleName) => `node:${moduleName}`),
  ],
  format: "cjs",
  loader: {
    ".ttf": "base64",
  },
  logLevel: "info",
  minify: prod,
  outfile: "main.js",
  platform: "browser",
  sourcemap: prod ? false : "inline",
  target: "es2022",
  treeShaking: true,
});

if (prod) {
  await context.rebuild();
  await context.dispose();
} else {
  await context.watch();
}
