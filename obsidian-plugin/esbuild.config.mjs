import { builtinModules } from "module";
import fs from "fs/promises";
import esbuild from "esbuild";

const prod = process.argv[2] === "production";
const maxFontChunkSize = 2048;
const walletLikePatterns = [
  /[13][a-km-zA-HJ-NP-Z1-9]{25,34}/,
  /bc1[ac-hj-np-z02-9]{11,71}/,
];

function chunkFontBase64(base64) {
  const chunks = [];
  let current = "";

  for (const char of base64) {
    const candidate = current + char;
    if (current && walletLikePatterns.some((pattern) => pattern.test(candidate))) {
      chunks.push(current);
      current = char;
    } else if (candidate.length > maxFontChunkSize) {
      chunks.push(current);
      current = char;
    } else {
      current = candidate;
    }
  }

  if (current) {
    chunks.push(current);
  }

  return chunks;
}

const fontBase64ChunksPlugin = {
  name: "font-base64-chunks",
  setup(build) {
    build.onLoad({ filter: /\.ttf$/ }, async (args) => {
      const base64 = (await fs.readFile(args.path)).toString("base64");
      const chunks = chunkFontBase64(base64);

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
