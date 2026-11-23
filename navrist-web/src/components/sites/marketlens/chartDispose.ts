// lightweight-charts 5 can run one last internal resize/paint callback after one of its panes or series has been removed (we remove and
// re-add overlay series, and rebuild the chart when the time axis changes), which throws "Object is disposed" from inside the library.
// The chart has already gone, nothing is lost. Swallow exactly that error (this message, raised from the library's resizeCanvasElement), so
// a real error of any other kind still shows. Installed once, when a chart component is first loaded in the browser.
if (typeof window !== "undefined") {
  window.addEventListener("error", (e) => {
    const stack = String((e.error as Error | undefined)?.stack ?? "");
    if (String(e.message || "").includes("Object is disposed") && stack.includes("resizeCanvasElement")) e.preventDefault();
  });
}

export function removeChartSafely(chart: { remove: () => void }): void {
  chart.remove();
}
