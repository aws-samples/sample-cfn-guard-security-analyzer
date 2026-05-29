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

  const onDiscover = useCallback(
    async (url: string) => {
      // Reset everything tied to the previous flow before starting a new one.
      analysis.clearBatch();
      setSelectedNames([]);
      await discover.discover(url);
    },
    [analysis, discover],
  );

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
      await analysis.analyzeBatch(urls);
    },
    [analysis],
  );

  // The "in flight" sense for InputSection: any of the discovery /
  // selection / batch-analysis steps is in progress.
  const inMultiResourceFlow =
    discover.status === "discovering" || analysis.batchAnalyzing;

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
            onDiscover={onDiscover}
            busy={inMultiResourceFlow}
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

          {showSelector && (
            <ResourceSelector
              resources={discover.resources}
              selectedNames={selectedNames}
              onToggle={onToggle}
              onSelectAll={onSelectAll}
              onClearSelection={onClearSelection}
              onAnalyzeBatch={onAnalyzeBatch}
              analyzing={analysis.batchAnalyzing}
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

          {analysis.status === "in_progress" && (
            <ProgressSection analysis={analysis} />
          )}
          {analysis.results.length > 0 && (
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
