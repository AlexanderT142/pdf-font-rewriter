import crypto from "crypto";
import fs from "fs/promises";
import http from "http";
import https from "https";
import { fileURLToPath } from "url";

export function joinReleaseUrl(baseUrl: string, fileName: string): string {
  return `${baseUrl.replace(/\/+$/, "")}/${encodeURIComponent(fileName)}`;
}

export async function downloadBuffer(url: string, redirects = 0): Promise<Buffer> {
  if (url.startsWith("file:")) {
    return fs.readFile(fileURLToPath(url));
  }

  if (redirects > 5) {
    throw new Error(`Too many redirects while downloading ${url}`);
  }

  return new Promise((resolve, reject) => {
    const client = url.startsWith("https:") ? https : http;
    const request = client.get(
      url,
      {
        headers: {
          "User-Agent": "pdf-font-rewriter-obsidian",
        },
      },
      (response) => {
        const statusCode = response.statusCode ?? 0;
        const location = response.headers.location;

        if (statusCode >= 300 && statusCode < 400 && location) {
          response.resume();
          const redirectUrl = new URL(location, url).toString();
          downloadBuffer(redirectUrl, redirects + 1).then(resolve, reject);
          return;
        }

        if (statusCode !== 200) {
          response.resume();
          reject(new Error(`Download failed with HTTP ${statusCode}: ${url}`));
          return;
        }

        const chunks: Buffer[] = [];
        response.on("data", (chunk: Buffer) => chunks.push(chunk));
        response.on("end", () => resolve(Buffer.concat(chunks)));
      },
    );

    request.on("error", reject);
  });
}

export async function assertReadableFile(filePath: string, label: string): Promise<void> {
  if (!filePath) {
    throw new Error(`Missing ${label} path.`);
  }

  try {
    await fs.access(filePath);
  } catch {
    throw new Error(`Cannot read ${label}: ${filePath}`);
  }
}

export async function sha256File(filePath: string): Promise<string> {
  const buffer = await fs.readFile(filePath);
  return sha256Buffer(buffer);
}

export function sha256Buffer(buffer: Buffer): string {
  return crypto.createHash("sha256").update(buffer).digest("hex");
}

export async function removeIfExists(filePath: string): Promise<void> {
  try {
    await fs.unlink(filePath);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
      throw error;
    }
  }
}
