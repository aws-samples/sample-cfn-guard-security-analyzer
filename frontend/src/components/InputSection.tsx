import { useState } from "react";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Button from "@cloudscape-design/components/button";
import SegmentedControl from "@cloudscape-design/components/segmented-control";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Box from "@cloudscape-design/components/box";
import type { UseAnalysisReturn } from "../hooks/useAnalysis";
import type { AnalysisType } from "../types";
import { looksLikeServiceIndexUrl } from "../hooks/useDiscover";

/**
 * Quick-pick sample URLs shown under the input. The first three are
 * single-resource pages (Quick Scan flow). The last three are service-index
 * pages that route to the discover-and-select flow. Mixing both shapes lets a
 * first-time user see *both* flows without knowing the URL conventions.
 */
const SAMPLE_URLS: ReadonlyArray<{
  label: string;
  url: string;
  /** "single" -> immediate quick scan. "index" -> discover flow. */
  kind: "single" | "index";
}> = [
  {
    label: "S3 Bucket",
    url: "https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-s3-bucket.html",
    kind: "single",
  },
  {
    label: "IAM Role",
    url: "https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-iam-role.html",
    kind: "single",
  },
  {
    label: "Lambda Function",
    url: "https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-lambda-function.html",
    kind: "single",
  },
  {
    label: "All S3 resources",
    url: "https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/AWS_S3.html",
    kind: "index",
  },
  {
    label: "All IAM resources",
    url: "https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/AWS_IAM.html",
    kind: "index",
  },
  {
    label: "Bedrock AgentCore (all)",
    url: "https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/AWS_BedrockAgentCore.html",
    kind: "index",
  },
];

interface InputSectionProps {
  analysis: UseAnalysisReturn;
  /** Phase 6: triggered when the user submits an index URL. */
  onDiscover?: (url: string) => void;
  /** True while a discover or batch flow is in progress. */
  busy?: boolean;
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
 *
 * Phase 6 addition: when the URL looks like a CFN service-index page
 * (`AWS_<Service>.html`), the form switches to "Discover Resources" mode
 * which calls `POST /analysis/discover` instead of `POST /analysis/quick`.
 * URLs that don't match the index pattern continue to use the single-URL
 * flow unchanged.
 *
 * Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7
 */
export default function InputSection({
  analysis,
  onDiscover,
  busy = false,
}: InputSectionProps) {
  const [url, setUrl] = useState("");
  const [analysisType, setAnalysisType] = useState<AnalysisType>("quick");
  const [urlError, setUrlError] = useState("");

  // Auto-detect: if the URL matches the CFN index pattern (AWS_<Service>.html),
  // we route to discovery instead of single-URL analysis. The user can still
  // override by toggling between "Single resource" and "Discover service"
  // segmented control if both makes sense for their input.
  const isIndexUrl = looksLikeServiceIndexUrl(url);
  const isInProgress = analysis.status === "in_progress" || busy;

  const handleSubmit = () => {
    if (!validateUrl(url)) {
      setUrlError("Please enter a valid CloudFormation documentation URL.");
      return;
    }
    setUrlError("");

    if (isIndexUrl && onDiscover) {
      onDiscover(url);
      return;
    }

    analysis.startAnalysis(url, analysisType);
  };

  return (
    <Container
      header={<Header variant="h2">Analyze CloudFormation Documentation</Header>}
    >
      <SpaceBetween size="l">
        <FormField
          label="CloudFormation Documentation URL"
          description={
            isIndexUrl
              ? "Detected service index URL — clicking the button below discovers the resources documented on this page."
              : "Paste a CFN resource page URL for single-resource analysis, or a service index URL (AWS_<Service>.html) to discover and batch-analyze."
          }
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

        <FormField
          label="Try a sample"
          description="Single-resource pages run a Quick Scan. 'All …' pages discover every resource in that service so you can pick which to analyze."
        >
          <SpaceBetween direction="horizontal" size="xs">
            {SAMPLE_URLS.map((s) => (
              <Button
                key={s.url}
                disabled={isInProgress}
                onClick={() => {
                  setUrl(s.url);
                  if (urlError) setUrlError("");
                }}
                iconName={s.kind === "index" ? "folder" : "file"}
              >
                {s.label}
              </Button>
            ))}
          </SpaceBetween>
          <Box variant="small" color="text-status-inactive" margin={{ top: "xs" }}>
            Click a sample to fill the URL above, then press the action button.
          </Box>
        </FormField>

        {!isIndexUrl && (
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
        )}

        <Button
          variant="primary"
          onClick={handleSubmit}
          disabled={isInProgress}
          loading={isInProgress}
        >
          {isIndexUrl ? "Discover Resources" : "Start Security Analysis"}
        </Button>
      </SpaceBetween>
    </Container>
  );
}
