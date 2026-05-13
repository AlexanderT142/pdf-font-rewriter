import esbuild from "esbuild";
import fs from "fs/promises";
import os from "os";
import path from "path";
import { fileURLToPath, pathToFileURL } from "url";

const pluginRoot = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const repoRoot = path.dirname(pluginRoot);
const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), "pdf-font-rewriter-test-bundle-"));
const outfile = path.join(tempDir, "helper-installer-test.mjs");

await esbuild.build({
  absWorkingDir: pluginRoot,
  alias: {
    obsidian: path.join(pluginRoot, "scripts", "obsidian-test-stub.ts"),
  },
  bundle: true,
  entryPoints: ["scripts/helper-installer-test-entry.ts"],
  format: "esm",
  outfile,
  platform: "node",
  target: "node22",
});

process.env.PDF_FONT_REWRITER_RELEASE_DIR = path.join(repoRoot, "release", "helper");
await import(pathToFileURL(outfile).toString());
