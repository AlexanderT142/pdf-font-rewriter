import os from "os";
import path from "path";

export function defaultHelperPath(): string {
  if (process.platform === "darwin") {
    return path.join(os.homedir(), "Library", "Application Support", "pdf-font-rewriter", "bin", executableName());
  }

  if (process.platform === "win32") {
    return path.join(os.homedir(), "AppData", "Roaming", "pdf-font-rewriter", "bin", executableName());
  }

  return path.join(os.homedir(), ".local", "share", "pdf-font-rewriter", "bin", executableName());
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
