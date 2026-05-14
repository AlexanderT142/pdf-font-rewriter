export const HELPER_VERSION = "0.1.17";
export const HELPER_MANIFEST_NAME = "helper-manifest.json";
export const DEFAULT_HELPER_RELEASE_BASE_URL =
  "https://github.com/AlexanderT142/pdf-font-rewriter/releases/download/0.1.17";

export interface HelperAsset {
  name: string;
  platform: string;
  sha256: string;
  size_bytes: number;
}

export interface HelperManifest {
  version: string;
  assets: Record<string, HelperAsset>;
}
