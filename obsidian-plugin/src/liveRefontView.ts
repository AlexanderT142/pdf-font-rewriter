import { FileView, Notice, TFile, WorkspaceLeaf } from "obsidian";
import {
  AnnotationLayer,
  AnnotationMode,
  OPS,
  TextLayer,
  getDocument,
  setLayerDimensions,
  version as pdfjsVersion,
  type PDFDocumentLoadingTask,
  type PDFDocumentProxy,
  type PDFPageProxy,
  type PageViewport,
  type RenderTask,
} from "pdfjs-dist/legacy/build/pdf.mjs";
import { WorkerMessageHandler } from "pdfjs-dist/legacy/build/pdf.worker.mjs";

import { LiveRefontClient } from "./liveRefontClient";
import type { LiveRefontDrawRun, LiveRefontPagePlan } from "./liveRefontProtocol";
import type PdfFontRewriterPlugin from "./main";

export const LIVE_REFONT_VIEW_TYPE = "pdf-font-rewriter-live-refont";

const DEFAULT_SCALE = 1.15;
const MIN_SCALE = 0.5;
const MAX_SCALE = 3.0;
const ZOOM_STEP = 0.15;
const OBSERVER_ROOT_MARGIN = "1400px 0px";

type PdfJsWorkerWindow = typeof window & {
  pdfjsWorker?: { WorkerMessageHandler: unknown };
};

(window as PdfJsWorkerWindow).pdfjsWorker ??= { WorkerMessageHandler };

interface PageRenderState {
  pageIndex: number;
  pageEl: HTMLElement;
  canvas: HTMLCanvasElement;
  textlessCanvas: HTMLCanvasElement;
  overlayCanvas: HTMLCanvasElement;
  textLayerEl: HTMLDivElement;
  annotationLayerEl: HTMLDivElement;
  statusEl: HTMLDivElement;
  generation: number;
  renderedScale: number | null;
  renderedPlanScale: number | null;
  pageProxy: PDFPageProxy | null;
  renderTask: RenderTask | null;
  textlessRenderTask: RenderTask | null;
  textLayer: TextLayer | null;
  annotationLayer: AnnotationLayer | null;
  plan: LiveRefontPagePlan | null;
  textOperationIndexes: Set<number> | null;
}

interface PageCoverageState {
  status: "refonted" | "original";
  retainedCount: number;
  reason: string;
}

export class LiveRefontPdfView extends FileView {
  private plugin: PdfFontRewriterPlugin;
  private toolbarEl: HTMLElement | null = null;
  private scrollerEl: HTMLElement | null = null;
  private statusEl: HTMLElement | null = null;
  private pdfDocument: PDFDocumentProxy | null = null;
  private loadingTask: PDFDocumentLoadingTask | null = null;
  private liveClient: LiveRefontClient | null = null;
  private observer: IntersectionObserver | null = null;
  private pages = new Map<number, PageRenderState>();
  private pageCoverage = new Map<number, PageCoverageState>();
  private pageCount = 0;
  private scale = DEFAULT_SCALE;
  private loadGeneration = 0;

  constructor(leaf: WorkspaceLeaf, plugin: PdfFontRewriterPlugin) {
    super(leaf);
    this.plugin = plugin;
    this.navigation = true;
  }

  getViewType(): string {
    return LIVE_REFONT_VIEW_TYPE;
  }

  getIcon(): string {
    return "type";
  }

  getDisplayText(): string {
    return this.file ? `${this.file.basename} (Live Refont)` : "Live Refont PDF";
  }

  canAcceptExtension(extension: string): boolean {
    return extension.toLowerCase() === "pdf";
  }

  async onLoadFile(file: TFile): Promise<void> {
    this.loadGeneration += 1;
    const generation = this.loadGeneration;
    this.renderShell(file);
    this.liveClient?.dispose();
    this.liveClient = new LiveRefontClient(this.plugin, file);
    await this.destroyPdfDocument();
    await this.loadPdf(file, generation);
  }

  async onUnloadFile(_file: TFile): Promise<void> {
    this.loadGeneration += 1;
    this.clearPageState();
    this.liveClient?.dispose();
    this.liveClient = null;
    await this.destroyPdfDocument();
    this.contentEl.empty();
  }

  private renderShell(file: TFile): void {
    this.contentEl.empty();
    this.contentEl.addClass("pdf-font-rewriter-live-view");
    this.pageCoverage.clear();
    this.pageCount = 0;

    this.toolbarEl = this.contentEl.createDiv({ cls: "pdf-font-rewriter-live-toolbar" });
    const titleEl = this.toolbarEl.createDiv({ cls: "pdf-font-rewriter-live-title" });
    titleEl.setText(file.path);

    const actionsEl = this.toolbarEl.createDiv({ cls: "pdf-font-rewriter-live-actions" });
    this.addToolbarButton(actionsEl, "Zoom out", "-", () => {
      void this.setScale(this.scale - ZOOM_STEP);
    });
    this.addToolbarButton(actionsEl, "Reset zoom", "100%", () => {
      void this.setScale(DEFAULT_SCALE);
    });
    this.addToolbarButton(actionsEl, "Zoom in", "+", () => {
      void this.setScale(this.scale + ZOOM_STEP);
    });

    this.statusEl = this.toolbarEl.createDiv({ cls: "pdf-font-rewriter-live-status" });
    this.statusEl.setText(`PDF.js ${pdfjsVersion}: loading`);

    this.scrollerEl = this.contentEl.createDiv({ cls: "pdf-font-rewriter-live-scroller" });
  }

  private addToolbarButton(
    parent: HTMLElement,
    label: string,
    text: string,
    onClick: () => void,
  ): void {
    const button = parent.createEl("button", {
      cls: "pdf-font-rewriter-live-button",
      text,
    });
    button.setAttribute("aria-label", label);
    button.setAttribute("title", label);
    button.addEventListener("click", onClick);
  }

  private async loadPdf(file: TFile, generation: number): Promise<void> {
    if (!this.scrollerEl || !this.statusEl) {
      return;
    }

    try {
      const data = new Uint8Array(await this.plugin.app.vault.readBinary(file));
      this.loadingTask = getDocument({
        data,
        useWorkerFetch: false,
        useSystemFonts: true,
        isOffscreenCanvasSupported: false,
        isImageDecoderSupported: false,
      });
      const pdfDocument = await this.loadingTask.promise;
      if (generation !== this.loadGeneration) {
        await pdfDocument.destroy();
        return;
      }

      this.pdfDocument = pdfDocument;
      this.pageCount = pdfDocument.numPages;
      this.createPageShells(this.pageCount);
      this.updateToolbarCoverage();
    } catch (error) {
      console.error(error);
      this.statusEl.setText("Live view failed to load PDF.");
      new Notice("PDF Font Rewriter: Live Refont View could not load this PDF.");
    }
  }

  private createPageShells(pageCount: number): void {
    if (!this.scrollerEl) {
      return;
    }

    this.clearPageState();
    this.pageCoverage.clear();
    this.observer = new IntersectionObserver((entries) => this.handleIntersection(entries), {
      root: this.scrollerEl,
      rootMargin: OBSERVER_ROOT_MARGIN,
      threshold: 0.01,
    });

    for (let pageIndex = 0; pageIndex < pageCount; pageIndex += 1) {
      const pageEl = this.scrollerEl.createDiv({ cls: "pdf-font-rewriter-live-page" });
      pageEl.setAttribute("data-page-index", String(pageIndex));
      pageEl.setCssProps({
        "--total-scale-factor": String(this.scale),
        "--scale-round-x": "1px",
        "--scale-round-y": "1px",
      });

      const pageHeaderEl = pageEl.createDiv({ cls: "pdf-font-rewriter-live-page-header" });
      pageHeaderEl.setText(`Page ${pageIndex + 1}`);

      const surfaceEl = pageEl.createDiv({ cls: "pdf-font-rewriter-live-surface" });
      const canvas = surfaceEl.createEl("canvas", {
        cls: "pdf-font-rewriter-live-canvas",
      });
      const textlessCanvas = this.contentEl.ownerDocument.createElement("canvas");
      const overlayCanvas = surfaceEl.createEl("canvas", {
        cls: "pdf-font-rewriter-live-refont-overlay",
      });
      const textLayerEl = surfaceEl.createDiv({ cls: "textLayer pdf-font-rewriter-live-text-layer" });
      const annotationLayerEl = surfaceEl.createDiv({
        cls: "annotationLayer pdf-font-rewriter-live-annotation-layer",
      });
      const statusEl = pageEl.createDiv({ cls: "pdf-font-rewriter-live-page-status" });
      statusEl.setText("Waiting for viewport");

      const state: PageRenderState = {
        pageIndex,
        pageEl,
        canvas,
        textlessCanvas,
        overlayCanvas,
        textLayerEl,
        annotationLayerEl,
        statusEl,
        generation: 0,
        renderedScale: null,
        renderedPlanScale: null,
        pageProxy: null,
        renderTask: null,
        textlessRenderTask: null,
        textLayer: null,
        annotationLayer: null,
        plan: null,
        textOperationIndexes: null,
      };
      this.pages.set(pageIndex, state);
      this.observer.observe(pageEl);
    }
  }

  private handleIntersection(entries: IntersectionObserverEntry[]): void {
    for (const entry of entries) {
      if (!entry.isIntersecting) {
        continue;
      }
      const pageIndex = Number((entry.target as HTMLElement).dataset.pageIndex);
      if (Number.isInteger(pageIndex)) {
        this.renderPage(pageIndex).catch((error: unknown) => {
          console.error(error);
          const state = this.pages.get(pageIndex);
          if (state) {
            state.statusEl.setText("Render failed");
            this.recordOriginalOnlyPage(pageIndex, "render failed");
          }
        });
      }
    }
  }

  private async renderPage(pageIndex: number): Promise<void> {
    const state = this.pages.get(pageIndex);
    if (!state || !this.pdfDocument) {
      return;
    }
    if (state.renderedScale === this.scale) {
      return;
    }

    state.generation += 1;
    const generation = state.generation;
    state.statusEl.setText("Rendering original PDF page");
    this.cancelPageRender(state);

    const page = state.pageProxy ?? (await this.pdfDocument.getPage(pageIndex + 1));
    if (generation !== state.generation) {
      return;
    }

    state.pageProxy = page;
    const viewport = page.getViewport({ scale: this.scale });
    this.sizePageSurface(state, viewport);

    const context = state.canvas.getContext("2d");
    if (!context) {
      state.statusEl.setText("Canvas context unavailable");
      return;
    }

    context.clearRect(0, 0, state.canvas.width, state.canvas.height);
    const outputScale = window.devicePixelRatio || 1;
    const renderTask = page.render({
      canvas: null,
      canvasContext: context,
      viewport,
      transform: outputScale === 1 ? undefined : [outputScale, 0, 0, outputScale, 0, 0],
      annotationMode: AnnotationMode.DISABLE,
    });
    state.renderTask = renderTask;
    await renderTask.promise;
    if (generation !== state.generation) {
      return;
    }

    await this.renderTextLayer(state, page, viewport, generation);
    await this.renderAnnotationLayer(state, page, viewport, generation);
    state.renderedScale = this.scale;
    state.statusEl.setText("Original rendered; requesting live refont plan");
    await this.applyLiveRefontPlan(state, page, viewport, generation);
  }

  private sizePageSurface(state: PageRenderState, viewport: PageViewport): void {
    const outputScale = window.devicePixelRatio || 1;
    const width = Math.floor(viewport.width);
    const height = Math.floor(viewport.height);
    const pixelWidth = Math.max(1, Math.floor(viewport.width * outputScale));
    const pixelHeight = Math.max(1, Math.floor(viewport.height * outputScale));

    state.pageEl.setCssProps({ "--total-scale-factor": String(this.scale) });
    state.pageEl.setCssStyles({
      width: `${width}px`,
      minHeight: `${height}px`,
    });

    const surfaceEl = state.canvas.parentElement;
    if (surfaceEl) {
      surfaceEl.setCssStyles({
        width: `${width}px`,
        height: `${height}px`,
      });
    }

    state.canvas.width = pixelWidth;
    state.canvas.height = pixelHeight;
    state.canvas.setCssStyles({
      width: `${width}px`,
      height: `${height}px`,
    });
    state.overlayCanvas.width = pixelWidth;
    state.overlayCanvas.height = pixelHeight;
    state.overlayCanvas.setCssStyles({
      width: `${width}px`,
      height: `${height}px`,
    });
    state.textlessCanvas.width = pixelWidth;
    state.textlessCanvas.height = pixelHeight;
    setLayerDimensions(state.textLayerEl, viewport);
    setLayerDimensions(state.annotationLayerEl, viewport);
  }

  private async renderTextLayer(
    state: PageRenderState,
    page: PDFPageProxy,
    viewport: PageViewport,
    generation: number,
  ): Promise<void> {
    state.textLayer?.cancel();
    state.textLayerEl.empty();
    const textContent = await page.getTextContent();
    if (generation !== state.generation) {
      return;
    }

    const textLayer = new TextLayer({
      textContentSource: textContent,
      container: state.textLayerEl,
      viewport,
    });
    state.textLayer = textLayer;
    await textLayer.render();
  }

  private async renderAnnotationLayer(
    state: PageRenderState,
    page: PDFPageProxy,
    viewport: PageViewport,
    generation: number,
  ): Promise<void> {
    state.annotationLayerEl.empty();
    state.annotationLayer = null;
    const annotations = await page.getAnnotations({ intent: "display" });
    if (generation !== state.generation || annotations.length === 0) {
      return;
    }

    const layerViewport = viewport.clone({ dontFlip: true });
    const linkService = this.annotationLinkService();
    const annotationLayer = new AnnotationLayer({
      div: state.annotationLayerEl,
      accessibilityManager: null,
      annotationCanvasMap: null,
      annotationEditorUIManager: null,
      annotationStorage: this.pdfDocument?.annotationStorage ?? null,
      page,
      viewport: layerViewport,
      structTreeLayer: null,
      commentManager: null,
      linkService,
    });
    state.annotationLayer = annotationLayer;
    await annotationLayer.render({
      annotations,
      div: state.annotationLayerEl,
      page,
      viewport: layerViewport,
      linkService,
      annotationStorage: this.pdfDocument?.annotationStorage,
      renderForms: true,
      enableScripting: false,
      hasJSActions: false,
      fieldObjects: null,
    });
  }

  private annotationLinkService(): any {
    return {
      eventBus: { dispatch: () => undefined },
      externalLinkTarget: 2,
      isInPresentationMode: false,
      pagesCount: this.pageCount,
      page: this.visiblePageIndexes()[0] + 1 || 1,
      rotation: 0,
      addLinkAttributes: (link: HTMLAnchorElement, url: string, newWindow?: boolean): void => {
        link.href = url;
        link.target = newWindow === false ? "_self" : "_blank";
        link.rel = "noopener noreferrer";
      },
      getAnchorUrl: (anchor: string): string => (anchor ? `#${anchor}` : "#"),
      getDestinationHash: (_destination: unknown): string => "#",
      goToDestination: (destination: unknown): Promise<void> => this.goToPdfDestination(destination),
      executeNamedAction: (action: string): void => this.executePdfNamedAction(action),
      executeSetOCGState: (_action: unknown): void => undefined,
    };
  }

  private async goToPdfDestination(destination: unknown): Promise<void> {
    if (!this.pdfDocument) {
      return;
    }

    const explicitDestination =
      typeof destination === "string" ? await this.pdfDocument.getDestination(destination) : destination;
    if (!Array.isArray(explicitDestination) || explicitDestination.length === 0) {
      return;
    }

    const pageRef = explicitDestination[0];
    let pageIndex: number;
    if (typeof pageRef === "number") {
      pageIndex = pageRef;
    } else {
      pageIndex = await this.pdfDocument.getPageIndex(pageRef);
    }
    await this.scrollToPageIndex(pageIndex);
  }

  private executePdfNamedAction(action: string): void {
    const current = this.visiblePageIndexes()[0] ?? 0;
    const last = Math.max(0, this.pageCount - 1);
    const target = {
      FirstPage: 0,
      LastPage: last,
      NextPage: Math.min(last, current + 1),
      PrevPage: Math.max(0, current - 1),
    }[action];
    if (target !== undefined) {
      this.scrollToPageIndex(target).catch((error: unknown) => console.warn(error));
    }
  }

  private async scrollToPageIndex(pageIndex: number): Promise<void> {
    const state = this.pages.get(pageIndex);
    if (!state) {
      return;
    }
    state.pageEl.scrollIntoView({ block: "start" });
    await this.renderPage(pageIndex);
  }

  private async setScale(nextScale: number): Promise<void> {
    const bounded = Math.max(MIN_SCALE, Math.min(MAX_SCALE, Number(nextScale.toFixed(2))));
    if (bounded === this.scale) {
      return;
    }

    this.scale = bounded;
    for (const state of this.pages.values()) {
      state.renderedScale = null;
      state.renderedPlanScale = null;
      state.statusEl.setText("Zoom changed; waiting for viewport");
    }

    const visiblePages = this.visiblePageIndexes();
    await Promise.all(visiblePages.map((pageIndex) => this.renderPage(pageIndex)));
  }

  private visiblePageIndexes(): number[] {
    if (!this.scrollerEl) {
      return [];
    }

    const rootBounds = this.scrollerEl.getBoundingClientRect();
    const visible: number[] = [];
    for (const [pageIndex, state] of this.pages) {
      const rect = state.pageEl.getBoundingClientRect();
      if (rect.bottom >= rootBounds.top && rect.top <= rootBounds.bottom) {
        visible.push(pageIndex);
      }
    }
    return visible.slice(0, 6);
  }

  private cancelPageRender(state: PageRenderState): void {
    if (state.renderTask) {
      try {
        state.renderTask.cancel();
      } catch {
        // PDF.js may already have completed the task.
      }
      state.renderTask = null;
    }
    if (state.textlessRenderTask) {
      try {
        state.textlessRenderTask.cancel();
      } catch {
        // PDF.js may already have completed the task.
      }
      state.textlessRenderTask = null;
    }
    state.textLayer?.cancel();
    state.textLayer = null;
    state.annotationLayerEl.empty();
    state.annotationLayer = null;
    this.liveClient?.cancel(state.pageIndex);
  }

  private clearPageState(): void {
    this.observer?.disconnect();
    this.observer = null;

    for (const state of this.pages.values()) {
      state.generation += 1;
      this.cancelPageRender(state);
      state.pageProxy?.cleanup();
    }
    this.pages.clear();
    this.scrollerEl?.empty();
  }

  private async destroyPdfDocument(): Promise<void> {
    if (this.pdfDocument) {
      try {
        await this.pdfDocument.destroy();
      } catch {
        // The document may already be torn down by PDF.js.
      }
      this.pdfDocument = null;
    }
    if (this.loadingTask) {
      try {
        await this.loadingTask.destroy();
      } catch {
        // Ignore duplicate teardown.
      }
      this.loadingTask = null;
    }
  }

  private async applyLiveRefontPlan(
    state: PageRenderState,
    page: PDFPageProxy,
    viewport: PageViewport,
    generation: number,
  ): Promise<void> {
    if (!this.liveClient) {
      state.statusEl.setText("Original rendered; planner unavailable");
      this.recordOriginalOnlyPage(state.pageIndex, "planner unavailable");
      return;
    }
    if (state.renderedPlanScale === this.scale && state.plan) {
      return;
    }

    let plan: LiveRefontPagePlan;
    try {
      plan = state.plan ?? (await this.liveClient.planPage(state.pageIndex));
    } catch (error) {
      console.warn("PDF Font Rewriter: live planner unavailable.", error);
      this.clearOverlay(state);
      state.statusEl.setText("Original retained: planner unavailable");
      this.recordOriginalOnlyPage(state.pageIndex, "planner unavailable");
      return;
    }
    if (generation !== state.generation) {
      return;
    }
    state.plan = plan;

    if (plan.status === "error") {
      this.clearOverlay(state);
      state.statusEl.setText(plan.error ? `Planner error: ${plan.error}` : "Planner error");
      this.recordOriginalOnlyPage(state.pageIndex, plan.error || "planner error");
      return;
    }

    if (plan.drawRuns.length === 0 || plan.status === "original") {
      this.clearOverlay(state);
      state.renderedPlanScale = this.scale;
      const reason = plan.classification === "scanned" ? "scanned page" : "no safe text regions";
      state.statusEl.setText(`Original retained: ${reason}`);
      this.recordOriginalOnlyPage(state.pageIndex, reason);
      return;
    }

    if (plan.rotation !== 0) {
      this.clearOverlay(state);
      state.statusEl.setText("Original retained: rotated live overlay is not implemented yet");
      this.recordOriginalOnlyPage(state.pageIndex, "rotated page");
      return;
    }

    let fontFamily: string;
    try {
      fontFamily = await this.liveClient.targetFontFamily();
    } catch (error) {
      console.warn("PDF Font Rewriter: could not load live target font.", error);
      this.clearOverlay(state);
      state.statusEl.setText("Original retained: target font unavailable");
      this.recordOriginalOnlyPage(state.pageIndex, "target font unavailable");
      return;
    }
    if (generation !== state.generation) {
      return;
    }

    let erasedRegionIds: Set<string>;
    try {
      erasedRegionIds = await this.eraseSafeTextRegions(state, page, viewport, plan, generation);
    } catch (error) {
      console.warn("PDF Font Rewriter: textless erasure failed.", error);
      erasedRegionIds = new Set();
    }
    if (generation !== state.generation) {
      return;
    }
    if (erasedRegionIds.size === 0) {
      this.clearOverlay(state);
      state.renderedPlanScale = this.scale;
      state.statusEl.setText("Original retained: textless erasure unavailable");
      this.recordOriginalOnlyPage(state.pageIndex, "textless erasure unavailable");
      return;
    }

    this.drawRefontOverlay(state, viewport, plan, fontFamily, erasedRegionIds);
    state.renderedPlanScale = this.scale;
    const patchedRegions = plan.safeRegions.filter((region) => erasedRegionIds.has(region.id));
    const fallbackCount = patchedRegions.filter(
      (region) => region.plannerSafety === "live-fallback",
    ).length;
    const retainedCount = plan.safeRegions.length - erasedRegionIds.size + plan.unsafeRegions.length;
    const fallbackText = fallbackCount ? ` (${fallbackCount} live fallback)` : "";
    state.statusEl.setText(
      `Live refonted: ${erasedRegionIds.size} regions patched${fallbackText}, ${retainedCount} retained`,
    );
    this.recordRefontedPage(state.pageIndex, retainedCount);
  }

  private async eraseSafeTextRegions(
    state: PageRenderState,
    page: PDFPageProxy,
    viewport: PageViewport,
    plan: LiveRefontPagePlan,
    generation: number,
  ): Promise<Set<string>> {
    const textlessContext = state.textlessCanvas.getContext("2d");
    const pageContext = state.canvas.getContext("2d");
    if (!textlessContext || !pageContext) {
      return new Set();
    }

    const textOperationIndexes = await this.getTextOperationIndexes(state, page);
    if (generation !== state.generation || textOperationIndexes.size === 0) {
      return new Set();
    }

    const outputScale = window.devicePixelRatio || 1;
    textlessContext.clearRect(0, 0, state.textlessCanvas.width, state.textlessCanvas.height);
    const renderTask = page.render({
      canvas: null,
      canvasContext: textlessContext,
      viewport,
      transform: outputScale === 1 ? undefined : [outputScale, 0, 0, outputScale, 0, 0],
      annotationMode: AnnotationMode.DISABLE,
      operationsFilter: (index: number) => !textOperationIndexes.has(index),
    });
    state.textlessRenderTask = renderTask;
    await renderTask.promise;
    state.textlessRenderTask = null;
    if (generation !== state.generation) {
      return new Set();
    }

    return this.patchCanvasFromTextless(state, plan, viewport);
  }

  private async getTextOperationIndexes(
    state: PageRenderState,
    page: PDFPageProxy,
  ): Promise<Set<number>> {
    if (state.textOperationIndexes) {
      return state.textOperationIndexes;
    }

    const operatorList = await page.getOperatorList({ annotationMode: AnnotationMode.DISABLE });
    const fnArray = operatorList.fnArray as number[];
    const textPaintOps = new Set<number>([
      OPS.showText,
      OPS.showSpacedText,
      OPS.nextLineShowText,
      OPS.nextLineSetSpacingShowText,
    ]);
    const indexes = new Set<number>();
    fnArray.forEach((operation, index) => {
      if (textPaintOps.has(operation)) {
        indexes.add(index);
      }
    });
    state.textOperationIndexes = indexes;
    return indexes;
  }

  private patchCanvasFromTextless(
    state: PageRenderState,
    plan: LiveRefontPagePlan,
    viewport: PageViewport,
  ): Set<string> {
    const pageContext = state.canvas.getContext("2d");
    const textlessContext = state.textlessCanvas.getContext("2d");
    if (!pageContext || !textlessContext) {
      return new Set();
    }

    const [x0, y0, x1, y1] = plan.pageBox;
    const pageWidth = Math.max(1, x1 - x0);
    const pageHeight = Math.max(1, y1 - y0);
    const scaleX = viewport.width / pageWidth;
    const scaleY = viewport.height / pageHeight;
    const outputScale = window.devicePixelRatio || 1;
    const patchedRegionIds = new Set<string>();

    for (const region of plan.safeRegions) {
      const padding = Math.ceil(region.erasePaddingPxAt1x * outputScale);
      const [rx0, ry0, rx1, ry1] = region.bboxPdf;
      const left = Math.max(0, Math.floor((rx0 - x0) * scaleX * outputScale) - padding);
      const top = Math.max(0, Math.floor((ry0 - y0) * scaleY * outputScale) - padding);
      const right = Math.min(
        state.canvas.width,
        Math.ceil((rx1 - x0) * scaleX * outputScale) + padding,
      );
      const bottom = Math.min(
        state.canvas.height,
        Math.ceil((ry1 - y0) * scaleY * outputScale) + padding,
      );
      const width = right - left;
      const height = bottom - top;
      if (width <= 0 || height <= 0) {
        continue;
      }

      const pageImage = pageContext.getImageData(left, top, width, height);
      const textlessImage = textlessContext.getImageData(left, top, width, height);
      const diffRatio = patchTextPixels(pageImage.data, textlessImage.data);
      if (diffRatio <= 0 || diffRatio > 0.55) {
        continue;
      }

      pageContext.putImageData(pageImage, left, top);
      patchedRegionIds.add(region.id);
    }

    return patchedRegionIds;
  }

  private drawRefontOverlay(
    state: PageRenderState,
    viewport: PageViewport,
    plan: LiveRefontPagePlan,
    fontFamily: string,
    regionIds: Set<string>,
  ): void {
    const context = state.overlayCanvas.getContext("2d");
    if (!context) {
      state.statusEl.setText("Overlay canvas context unavailable");
      return;
    }

    const outputScale = window.devicePixelRatio || 1;
    context.clearRect(0, 0, state.overlayCanvas.width, state.overlayCanvas.height);
    context.setTransform(outputScale, 0, 0, outputScale, 0, 0);
    context.textBaseline = "alphabetic";

    const [x0, y0, x1, y1] = plan.pageBox;
    const pageWidth = Math.max(1, x1 - x0);
    const pageHeight = Math.max(1, y1 - y0);
    const scaleX = viewport.width / pageWidth;
    const scaleY = viewport.height / pageHeight;

    for (const run of plan.drawRuns) {
      if (!regionIds.has(run.regionId) || !isDrawableRun(run)) {
        continue;
      }
      const [r, g, b, a] = run.color;
      const x = (run.matrixPdf[4] - x0) * scaleX;
      const y = (run.matrixPdf[5] - y0) * scaleY;
      const fontSize = run.fontSize * scaleY;

      context.save();
      context.fillStyle = `rgba(${r}, ${g}, ${b}, ${a})`;
      context.font = `${fontSize}px "${fontFamily}"`;
      context.translate(x, y);
      context.scale(run.scaleX, 1);
      context.fillText(run.text, 0, 0);
      context.restore();
    }
    context.setTransform(1, 0, 0, 1, 0, 0);
  }

  private clearOverlay(state: PageRenderState): void {
    const context = state.overlayCanvas.getContext("2d");
    context?.clearRect(0, 0, state.overlayCanvas.width, state.overlayCanvas.height);
  }

  private recordRefontedPage(pageIndex: number, retainedCount: number): void {
    this.pageCoverage.set(pageIndex, {
      status: "refonted",
      retainedCount,
      reason: retainedCount ? "some regions retained" : "",
    });
    this.updateToolbarCoverage();
  }

  private recordOriginalOnlyPage(pageIndex: number, reason: string): void {
    this.pageCoverage.set(pageIndex, {
      status: "original",
      retainedCount: 1,
      reason,
    });
    this.updateToolbarCoverage();
  }

  private updateToolbarCoverage(): void {
    if (!this.statusEl || this.pageCount <= 0) {
      return;
    }

    const entries = [...this.pageCoverage.entries()];
    const originalOnly = entries
      .filter(([, coverage]) => coverage.status === "original")
      .map(([pageIndex]) => pageIndex + 1)
      .sort((left, right) => left - right);
    const partialCount = entries.filter(
      ([, coverage]) => coverage.status === "refonted" && coverage.retainedCount > 0,
    ).length;
    const pagePreview = originalOnly.slice(0, 6).join(", ");
    const remaining = originalOnly.length > 6 ? "..." : "";
    const leftText = originalOnly.length ? ` | left original: ${pagePreview}${remaining}` : "";
    const partialText = partialCount ? `, partial ${partialCount}` : "";

    this.statusEl.setText(
      `Live view ready: ${this.pageCount} pages | checked ${entries.length}, original-only ${originalOnly.length}${partialText}${leftText}`,
    );
  }
}

function isDrawableRun(run: LiveRefontDrawRun): boolean {
  return run.direction === "ltr" && run.text.length > 0 && Number.isFinite(run.fontSize);
}

function patchTextPixels(pageData: Uint8ClampedArray, textlessData: Uint8ClampedArray): number {
  let changedPixels = 0;
  const pixelCount = pageData.length / 4;

  for (let index = 0; index < pageData.length; index += 4) {
    const diff =
      Math.abs(pageData[index] - textlessData[index]) +
      Math.abs(pageData[index + 1] - textlessData[index + 1]) +
      Math.abs(pageData[index + 2] - textlessData[index + 2]) +
      Math.abs(pageData[index + 3] - textlessData[index + 3]);
    if (diff < 28) {
      continue;
    }

    pageData[index] = textlessData[index];
    pageData[index + 1] = textlessData[index + 1];
    pageData[index + 2] = textlessData[index + 2];
    pageData[index + 3] = textlessData[index + 3];
    changedPixels += 1;
  }

  return changedPixels / Math.max(1, pixelCount);
}

export async function openLiveRefontView(
  plugin: PdfFontRewriterPlugin,
  file: TFile,
  newLeaf = false,
): Promise<void> {
  if (file.extension.toLowerCase() !== "pdf") {
    new Notice("PDF Font Rewriter: open a PDF file first.");
    return;
  }

  const leaf = plugin.app.workspace.getLeaf(newLeaf);
  await leaf.setViewState({
    type: LIVE_REFONT_VIEW_TYPE,
    state: { file: file.path },
    active: true,
  });
}
