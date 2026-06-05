import { useCallback, useState } from "react";
import AppLayout from "@cloudscape-design/components/app-layout";
import BreadcrumbGroup from "@cloudscape-design/components/breadcrumb-group";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Flashbar from "@cloudscape-design/components/flashbar";
import { useAnalysis } from "./hooks/useAnalysis";
import { useDiscover } from "./hooks/useDiscover";
import InputSection from "./components/InputSection";
import ProgressSection from "./components/ProgressSection";
import ResultsSection from "./components/ResultsSection";
import ResourceSelector, {
  MAX_BATCH,
  computeSelectAll,
} from "./components/ResourceSelector";
import BatchResultsSection from "./components/BatchResultsSection";
import BatchProgressSection from "./components/BatchProgressSection";
import DiscoverProgressSection from "./components/DiscoverProgressSection";

/**
 * Root application component.
 *
 * Phase 6 adds a multi-resource flow: when the user pastes a CFN service
 * index URL (e.g. AWS_S3.html), `InputSection` routes to
 * `useDiscover.discover()` instead of `useAnalysis.startAnalysis()`. The
 * discovered resources render in `ResourceSelector`; the user picks up to 5
 * and triggers `useAnalysis.analyzeBatch()`. Results display in
 * `BatchResultsSection` with one expandable section per resource.
 *
 * The single-resource flow (Phases 1–5) remains unchanged.
 *
 * Validates: Requirements 2.1, 2.2, 2.3
 */
function App() {
  const analysis = useAnalysis();
  const discover = useDiscover();
  const [selectedNames, setSelectedNames] = useState<string[]>([]);

  // Wipe EVERY result surface before starting any new search. The app renders
  // three independent result stores — single-analysis (`analysis.results`),
  // batch (`analysis.batchResponse`), and discovery (`discover.resources`) —
  // and previously each flow only cleared its own. That left a prior detailed
  // scan stacked under a fresh discover/batch, so the user couldn't tell which
  // result was current. Clearing all three on every entry point keeps exactly
  // one flow visible at a time. (A "minimize to resume" history feature can
  // layer on top later; this is the correctness fix.)
  const resetAllFlows = useCallback(() => {
    analysis.resetAnalysis();
    analysis.clearBatch();
    discover.clear();
    setSelectedNames([]);
  }, [analysis, discover]);

  const onDiscover = useCallback(
    async (url: string) => {
      resetAllFlows();
      await discover.discover(url);
    },
    [discover, resetAllFlows],
  );

  // Refresh re-runs discovery against the same index URL with the cache
  // bypass. Keeps the current resource list visible until the fresh crawl
  // lands (discover() resets resources itself on start).
  const onRefreshDiscover = useCallback(() => {
    if (!discover.sourceUrl) return;
    void discover.discover(discover.sourceUrl, true);
  }, [discover]);

  const onToggle = useCallback((name: string) => {
    setSelectedNames((prev) =>
      prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name],
    );
  }, []);

  const onSelectAll = useCallback(() => {
    setSelectedNames(computeSelectAll(discover.resources));
  }, [discover.resources]);

  const onClearSelection = useCallback(() => setSelectedNames([]), []);

  const onAnalyzeBatch = useCallback(
    async (urls: string[]) => {
      if (urls.length === 0 || urls.length > MAX_BATCH) return;
      // Clear any leftover single-analysis result so it doesn't render beneath
      // the batch results. Keep discover.resources (the selector) — the batch
      // is launched FROM that selection, so the list must stay.
      analysis.resetAnalysis();
      await analysis.analyzeBatch(urls);
    },
    [analysis],
  );

  // Single-resource analysis is triggered from InputSection directly. Wrap it
  // so a fresh single scan also clears any prior batch/discovery results
  // (e.g. user discovered a service, then pasted a single resource URL).
  const onSingleAnalyze = useCallback(
    (url: string, type: Parameters<typeof analysis.startAnalysis>[1]) => {
      analysis.clearBatch();
      discover.clear();
      setSelectedNames([]);
      void analysis.startAnalysis(url, type);
    },
    [analysis, discover],
  );

  // The "in flight" sense for InputSection: any of the discovery /
  // selection / batch-analysis steps is in progress.
  const inMultiResourceFlow =
    discover.status === "discovering" || analysis.batchAnalyzing;

  // Global busy flag: ANY analysis in flight — single/detailed scan, discovery
  // crawl, or batch run. Only one analysis may run at a time, so every entry
  // point (single Start, Discover, batch Analyze) is disabled while this is
  // true. Prevents the conflict where a single scan and a batch run overlap.
  const anyRunning =
    analysis.status === "in_progress" ||
    analysis.batchAnalyzing ||
    discover.status === "discovering";

  // Show ResourceSelector once discovery succeeded and we haven't yet got
  // a batch response. Once batch results are in, switch to the results view.
  const showSelector =
    discover.status === "ready" && !analysis.batchResponse;

  return (
    <AppLayout
      breadcrumbs={
        <BreadcrumbGroup
          items={[{ text: "CloudFormation Security Analyzer", href: "#" }]}
        />
      }
      content={
        <SpaceBetween size="l">
          <InputSection
            analysis={analysis}
            onAnalyze={onSingleAnalyze}
            onDiscover={onDiscover}
            busy={anyRunning}
          />

          {discover.status === "error" && discover.error && (
            <Flashbar
              items={[
                {
                  type: "error",
                  content: discover.error,
                  dismissible: true,
                  onDismiss: () => discover.clear(),
                },
              ]}
            />
          )}

          {analysis.batchError && (
            <Flashbar
              items={[
                {
                  type: "error",
                  content: analysis.batchError,
                  dismissible: true,
                  onDismiss: () => analysis.clearBatch(),
                },
              ]}
            />
          )}

          {discover.status === "discovering" && (
            <DiscoverProgressSection
              discovering
              sourceUrl={discover.sourceUrl}
            />
          )}

          {showSelector && (
            <ResourceSelector
              resources={discover.resources}
              selectedNames={selectedNames}
              onToggle={onToggle}
              onSelectAll={onSelectAll}
              onClearSelection={onClearSelection}
              onAnalyzeBatch={onAnalyzeBatch}
              analyzing={analysis.batchAnalyzing}
              onRefresh={onRefreshDiscover}
              cached={discover.cached}
              cachedAt={discover.cachedAt}
            />
          )}

          {analysis.batchAnalyzing && !analysis.batchResponse && (
            <BatchProgressSection
              resourceNames={selectedNames}
              analyzing={analysis.batchAnalyzing}
            />
          )}

          {analysis.batchResponse && (
            <BatchResultsSection response={analysis.batchResponse} />
          )}

          {/* Single-resource progress/results are hidden whenever a
              multi-resource (discover/batch) flow is active or has results, so
              the two result surfaces are mutually exclusive on screen even
              mid-transition. resetAllFlows() already clears state on a new
              search; this guard is the belt-and-suspenders render gate. */}
          {!inMultiResourceFlow &&
            discover.status === "idle" &&
            !analysis.batchResponse &&
            analysis.status === "in_progress" && (
              <ProgressSection analysis={analysis} />
            )}
          {!inMultiResourceFlow &&
            discover.status === "idle" &&
            !analysis.batchResponse &&
            analysis.results.length > 0 && (
              <ResultsSection analysis={analysis} />
            )}
        </SpaceBetween>
      }
      navigationHide
      toolsHide
    />
  );
}

export default App;
