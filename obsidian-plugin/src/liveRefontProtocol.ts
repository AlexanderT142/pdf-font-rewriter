export interface LiveRefontPageRequest {
  pdfPath: string;
  pdfFingerprint: string;
  pageIndex: number;
  fontPath: string;
  fontHash: string;
  mode: "conservative" | "normal";
}

export interface LiveRefontPagePlan {
  pageIndex: number;
  status: "full" | "partial" | "original" | "error";
  classification: "native" | "scanned" | "hybrid" | "unknown" | "not_selected";
  pageBox: [number, number, number, number];
  rotation: number;
  safeRegions: LiveRefontSafeRegion[];
  drawRuns: LiveRefontDrawRun[];
  unsafeRegions: LiveRefontUnsafeRegion[];
  plannerVersion: string;
  error?: string;
}

export interface LiveRefontSafeRegion {
  id: string;
  bboxPdf: [number, number, number, number];
  erasePaddingPxAt1x: number;
  expectedText: string;
  plannerSafety?: "export-safe" | "live-fallback";
  reason?: string;
}

export interface LiveRefontDrawRun {
  id: string;
  regionId: string;
  text: string;
  matrixPdf: [number, number, number, number, number, number];
  fontSize: number;
  scaleX: number;
  color: [number, number, number, number];
  direction: "ltr" | "rtl" | "ttb" | "rotated" | "unknown";
  script: string;
  fontRole: string;
  fontPath: string;
  fit: {
    method: string;
    confidence: number;
    plannerSafety?: "export-safe" | "live-fallback";
    rawScaleX?: number;
    fontSizeMultiplier?: number;
    calibration?: string;
    calibrationFactor?: number;
    residualScaleX?: number;
    calibrationLines?: number;
    calibrationEvidence?: number;
    calibrationDispersion?: number;
    calibrationTail?: number;
    calibrationFallbackFraction?: number;
  };
}

export interface LiveRefontUnsafeRegion {
  bboxPdf: [number, number, number, number];
  reason: string;
  text: string;
}

export interface LiveRefontJsonRpcRequest {
  id: string;
  method: "planPage" | "cancel";
  params: LiveRefontPageRequest | { pageIndex: number };
}

export interface LiveRefontJsonRpcResponse {
  id: string;
  result?: LiveRefontPagePlan | { cancelled: true };
  error?: {
    code: string;
    message: string;
  };
}
