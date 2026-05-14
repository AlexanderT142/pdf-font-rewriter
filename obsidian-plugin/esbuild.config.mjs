import { builtinModules } from "module";
import fs from "fs/promises";
import esbuild from "esbuild";

const prod = process.argv[2] === "production";
const fontChunkSize = 16;

const fontBase64ChunksPlugin = {
  name: "font-base64-chunks",
  setup(build) {
    build.onLoad({ filter: /\.ttf$/ }, async (args) => {
      const base64 = (await fs.readFile(args.path)).toString("base64");
      const chunks = [];
      for (let index = 0; index < base64.length; index += fontChunkSize) {
        chunks.push(base64.slice(index, index + fontChunkSize));
      }

      return {
        contents: `export default ${JSON.stringify(chunks)};\n`,
        loader: "js",
      };
    });
  },
};

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
  logLevel: "info",
  minify: prod,
  outfile: "main.js",
  platform: "browser",
  plugins: [fontBase64ChunksPlugin],
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
