import os from "os";
import path from "path";

export function defaultHelperPath(): string {
  return path.join(defaultDataDir(), "bin", executableName());
}

export function defaultBuiltinFontsDir(): string {
  return path.join(defaultDataDir(), "fonts");
}

export function defaultReportsDir(): string {
  return path.join(defaultDataDir(), "reports");
}

function defaultDataDir(): string {
  if (process.platform === "darwin") {
    return path.join(os.homedir(), "Library", "Application Support", "pdf-font-rewriter");
  }

  if (process.platform === "win32") {
    return path.join(os.homedir(), "AppData", "Roaming", "pdf-font-rewriter");
  }

  return path.join(os.homedir(), ".local", "share", "pdf-font-rewriter");
}

export function executableName(): string {
  return process.platform === "win32" ? "refont-helper.exe" : "refont-helper";
}

export function platformTag(): string {
  const osName = platformOsName();
  const arch = platformArchName();
  return `${osName}-${arch}`;
}

function platformOsName(): string {
  if (process.platform === "darwin") {
    return "macos";
  }
  if (process.platform === "win32") {
    return "windows";
  }
  if (process.platform === "linux") {
    return "linux";
  }
  return process.platform;
}

function platformArchName(): string {
  if (process.arch === "arm64") {
    return "arm64";
  }
  if (process.arch === "x64") {
    return "x64";
  }
  return process.arch;
}
