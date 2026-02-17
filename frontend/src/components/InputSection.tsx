import { useState } from "react";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Button from "@cloudscape-design/components/button";
import SegmentedControl from "@cloudscape-design/components/segmented-control";
import SpaceBetween from "@cloudscape-design/components/space-between";
import type { UseAnalysisReturn } from "../hooks/useAnalysis";
import type { AnalysisType } from "../types";

interface InputSectionProps {
  analysis: UseAnalysisReturn;
}

/**
 * Returns true if the URL is valid (non-empty, non-whitespace-only).
 * Exported for property-based testing.
 * Validates: Requirement 3.5
 */
export function validateUrl(url: string): boolean {
  return url.trim().length > 0;
}

/**
 * Input form for starting a CloudFormation security analysis.
 * Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7
 */
export default function InputSection({ analysis }: InputSectionProps) {
  const [url, setUrl] = useState("");
  const [analysisType, setAnalysisType] = useState<AnalysisType>("quick");
  const [urlError, setUrlError] = useState("");

  const isInProgress = analysis.status === "in_progress";

  const handleSubmit = () => {
    if (!validateUrl(url)) {
      setUrlError("Please enter a valid CloudFormation documentation URL.");
      return;
    }
    setUrlError("");
    analysis.startAnalysis(url, analysisType);
  };

  return (
    <Container header={<Header variant="h2">Analyze CloudFormation Documentation</Header>}>
      <SpaceBetween size="l">
        <FormField
          label="CloudFormation Documentation URL"
          errorText={urlError}
        >
          <Input
            value={url}
            onChange={({ detail }) => {
              setUrl(detail.value);
              if (urlError) setUrlError("");
            }}
            placeholder="https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/..."
            disabled={isInProgress}
          />
        </FormField>

        <FormField label="Analysis Type">
          <SegmentedControl
            selectedId={analysisType}
            onChange={({ detail }) =>
              setAnalysisType(detail.selectedId as AnalysisType)
            }
            options={[
              { id: "quick", text: "Quick Scan" },
              { id: "detailed", text: "Detailed Analysis" },
            ]}
          />
        </FormField>

        <Button
          variant="primary"
          onClick={handleSubmit}
          disabled={isInProgress}
          loading={isInProgress}
        >
          Start Security Analysis
        </Button>
      </SpaceBetween>
    </Container>
  );
}
