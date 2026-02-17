import AppLayout from "@cloudscape-design/components/app-layout";
import BreadcrumbGroup from "@cloudscape-design/components/breadcrumb-group";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { useAnalysis } from "./hooks/useAnalysis";
import InputSection from "./components/InputSection";
import ProgressSection from "./components/ProgressSection";
import ResultsSection from "./components/ResultsSection";

/**
 * Root application component.
 * Composes InputSection, ProgressSection, and ResultsSection within
 * a Cloudscape AppLayout shell with breadcrumb navigation.
 *
 * Validates: Requirements 2.1, 2.2, 2.3
 */
function App() {
  const analysis = useAnalysis();

  return (
    <AppLayout
      breadcrumbs={
        <BreadcrumbGroup
          items={[
            { text: "CloudFormation Security Analyzer", href: "#" },
          ]}
        />
      }
      content={
        <SpaceBetween size="l">
          <InputSection analysis={analysis} />
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
