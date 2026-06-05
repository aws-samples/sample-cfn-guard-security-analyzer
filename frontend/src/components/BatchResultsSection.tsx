import { useState } from "react";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import Badge from "@cloudscape-design/components/badge";
import Box from "@cloudscape-design/components/box";
import ExpandableSection from "@cloudscape-design/components/expandable-section";
import KeyValuePairs from "@cloudscape-design/components/key-value-pairs";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Alert from "@cloudscape-design/components/alert";
import Flashbar from "@cloudscape-design/components/flashbar";
import SegmentedControl from "@cloudscape-design/components/segmented-control";
import type { BatchAnalysisResponse } from "../hooks/useAnalysis";
import type { PropertyData, RiskLevel } from "../types";
import { useGuardRules } from "../hooks/useGuardRules";
import {
  computeSeverityCounts,
  filterByRiskLevel,
  type FilterLevel,
} from "./ResultsSection";
import { formatCachedLabel } from "../utils/formatCachedLabel";
import PropertyCard from "./PropertyCard";
import GuardRuleModal from "./GuardRuleModal";

interface BatchResultsSectionProps {
  response: BatchAnalysisResponse;
}

const BADGE_COLOR: Record<RiskLevel, "red" | "grey" | "blue" | "green"> = {
  CRITICAL: "red",
  HIGH: "red",
  MEDIUM: "blue",
  LOW: "green",
};

/**
 * Best-effort coercion of a server-side property dict into our PropertyData
 * shape. The batch handler returns whatever the security-analyzer agent
 * produced, which usually matches PropertyData but occasionally lacks the
 * advisory fields. We default missing values to empty strings / arrays so
 * PropertyCard renders cleanly.
 *
 * Exported for unit testing.
 */
export function coerceProperty(raw: unknown): PropertyData {
  const r = (raw ?? {}) as Record<string, unknown>;
  const riskLevel = (r.risk_level || r.riskLevel || "MEDIUM") as RiskLevel;
  return {
    name: String(r.name ?? r.propertyName ?? ""),
    risk_level: ["CRITICAL", "HIGH", "MEDIUM", "LOW"].includes(riskLevel)
      ? riskLevel
      : "MEDIUM",
    description: String(r.description ?? ""),
    security_impact: String(
      r.security_impact ?? r.securityImplication ?? "",
    ),
    key_threat: String(r.key_threat ?? ""),
    secure_configuration: String(r.secure_configuration ?? ""),
    recommendation: String(r.recommendation ?? ""),
    property_path: String(r.property_path ?? ""),
    best_practices: Array.isArray(r.best_practices)
      ? (r.best_practices as string[])
      : [],
    common_misconfigurations: Array.isArray(r.common_misconfigurations)
      ? (r.common_misconfigurations as string[])
      : [],
  };
}

/**
 * Compute aggregate severity counts across all per-resource results in the
 * batch. Exported for unit testing.
 */
export function computeBatchSeverity(
  response: BatchAnalysisResponse,
): Record<RiskLevel, number> {
  const counts: Record<RiskLevel, number> = {
    CRITICAL: 0,
    HIGH: 0,
    MEDIUM: 0,
    LOW: 0,
  };
  for (const entry of Object.values(response.results)) {
    const props = entry.results?.properties;
    if (!Array.isArray(props)) continue;
    for (const p of props) {
      const coerced = coerceProperty(p);
      counts[coerced.risk_level] += 1;
    }
  }
  return counts;
}

/**
 * Aggregated batch results display. One ExpandableSection per resource so
 * users can drill into one resource at a time. Per-resource cache badges,
 * severity counts, and PropertyCard list.
 *
 * Errors from the batch endpoint are surfaced as Alert entries above the
 * successful results so they stay visible even when most resources analyzed
 * cleanly.
 */
export default function BatchResultsSection({
  response,
}: BatchResultsSectionProps) {
  const successKeys = Object.keys(response.results);
  const errorKeys = Object.keys(response.errors);
  const aggregateCounts = computeBatchSeverity(response);
  const totalProps = successKeys.reduce((sum, k) => {
    const props = response.results[k]?.results?.properties;
    return sum + (Array.isArray(props) ? props.length : 0);
  }, 0);

  // Guard-rule generation, identical to the single-resource ResultsSection so
  // every flow (quick, detailed, batch/discover) offers the same per-property
  // "Generate Guard Rule" action. Each batch resource carries its own URL +
  // type, so we resolve them per group before calling generateRule.
  const guardRules = useGuardRules();

  // Invert urlToKey (submission URL -> result key) so a result key maps back to
  // its source documentation URL, which guard-rule generation requires.
  const keyToUrl: Record<string, string> = {};
  for (const [url, key] of Object.entries(response.urlToKey ?? {})) {
    keyToUrl[key] = url;
  }

  const handleGenerateGuardRule = (
    property: PropertyData,
    resourceUrl: string,
    resourceType: string,
  ) => {
    guardRules.generateRule(property, resourceUrl, resourceType);
  };

  return (
    <Container
      header={
        <Header
          variant="h2"
          counter={`(${successKeys.length}/${response.count})`}
          description={`${totalProps} security properties across ${successKeys.length} resource${successKeys.length === 1 ? "" : "s"}.`}
        >
          Batch Analysis Results
        </Header>
      }
    >
      <SpaceBetween size="l">
        {guardRules.error && (
          <Flashbar
            items={[{
              type: "error",
              content: guardRules.error,
              dismissible: true,
              onDismiss: () => guardRules.clearError(),
            }]}
          />
        )}
        <KeyValuePairs
          columns={4}
          items={[
            {
              label: "Critical",
              value: <Badge color={BADGE_COLOR.CRITICAL}>{aggregateCounts.CRITICAL}</Badge>,
            },
            {
              label: "High",
              value: <Badge color={BADGE_COLOR.HIGH}>{aggregateCounts.HIGH}</Badge>,
            },
            {
              label: "Medium",
              value: <Badge color={BADGE_COLOR.MEDIUM}>{aggregateCounts.MEDIUM}</Badge>,
            },
            {
              label: "Low",
              value: <Badge color={BADGE_COLOR.LOW}>{aggregateCounts.LOW}</Badge>,
            },
          ]}
        />

        {errorKeys.length > 0 && (
          <Alert
            type="error"
            header={`${errorKeys.length} resource${errorKeys.length === 1 ? "" : "s"} failed to analyze`}
          >
            <SpaceBetween size="xs">
              {errorKeys.map((k) => (
                <Box key={k} variant="small">
                  <strong>{k}:</strong> {response.errors[k]}
                </Box>
              ))}
            </SpaceBetween>
          </Alert>
        )}

        {successKeys.length === 0 ? (
          <Box textAlign="center" color="inherit" padding="l">
            No successful analyses in this batch.
          </Box>
        ) : (
          successKeys.map((key) => {
            const entry = response.results[key];
            const props = Array.isArray(entry.results?.properties)
              ? (entry.results.properties as unknown[])
              : [];
            const coercedProps = props.map(coerceProperty);
            // Resolve this resource's source URL + CFN type for guard-rule
            // generation. resourceType comes from the analysis payload; the URL
            // from the inverted urlToKey map (fallback: the result key itself).
            const resourceUrl = keyToUrl[key] ?? "";
            const resourceType = String(entry.results?.resourceType ?? key);

            return (
              <ExpandableSection
                key={key}
                headerText={key}
                headerCounter={`(${coercedProps.length})`}
                headerActions={
                  entry.cached ? (
                    <StatusIndicator type="info">
                      {formatCachedLabel(entry.cached_at)}
                    </StatusIndicator>
                  ) : undefined
                }
              >
                <BatchResourcePanel
                  resourceKey={key}
                  properties={coercedProps}
                  onGenerateGuardRule={(prop) =>
                    handleGenerateGuardRule(prop, resourceUrl, resourceType)
                  }
                  generatingName={guardRules.generating}
                />
              </ExpandableSection>
            );
          })
        )}
      </SpaceBetween>

      <GuardRuleModal
        rule={guardRules.modalRule}
        onDismiss={guardRules.closeModal}
        onAddToCollection={(rule) => {
          guardRules.addToCollection(rule);
          guardRules.closeModal();
        }}
      />
    </Container>
  );
}

const SEVERITY_BADGE: Record<RiskLevel, "red" | "grey" | "blue" | "green"> =
  BADGE_COLOR;

/**
 * One resource's property list inside a batch result, with the SAME
 * All/Critical/High/Medium/Low severity filter as the single-resource
 * ResultsSection. Each resource owns its own filter state so filtering one
 * resource doesn't affect the others. This keeps the batch UI consistent with
 * single-scan instead of dumping every property in one flat list.
 */
function BatchResourcePanel({
  resourceKey,
  properties,
  onGenerateGuardRule,
  generatingName,
}: {
  resourceKey: string;
  properties: PropertyData[];
  onGenerateGuardRule: (property: PropertyData) => void;
  generatingName: string | null;
}) {
  const [filterLevel, setFilterLevel] = useState<FilterLevel>("ALL");

  if (properties.length === 0) {
    return (
      <Box variant="p" color="inherit">
        No properties returned for this resource.
      </Box>
    );
  }

  const counts = computeSeverityCounts(properties);
  const filtered = filterByRiskLevel(properties, filterLevel);

  return (
    <SpaceBetween size="m">
      <KeyValuePairs
        columns={4}
        items={[
          { label: "Critical", value: <Badge color={SEVERITY_BADGE.CRITICAL}>{counts.CRITICAL}</Badge> },
          { label: "High", value: <Badge color={SEVERITY_BADGE.HIGH}>{counts.HIGH}</Badge> },
          { label: "Medium", value: <Badge color={SEVERITY_BADGE.MEDIUM}>{counts.MEDIUM}</Badge> },
          { label: "Low", value: <Badge color={SEVERITY_BADGE.LOW}>{counts.LOW}</Badge> },
        ]}
      />
      <SegmentedControl
        selectedId={filterLevel}
        onChange={({ detail }) => setFilterLevel(detail.selectedId as FilterLevel)}
        options={[
          { id: "ALL", text: "All" },
          { id: "CRITICAL", text: "Critical" },
          { id: "HIGH", text: "High" },
          { id: "MEDIUM", text: "Medium" },
          { id: "LOW", text: "Low" },
        ]}
      />
      {filtered.length === 0 ? (
        <Box variant="p" color="inherit">
          No {filterLevel.toLowerCase()} properties for this resource.
        </Box>
      ) : (
        <SpaceBetween size="s">
          {filtered.map((p, i) => (
            <PropertyCard
              key={`${resourceKey}-${p.name}-${i}`}
              property={p}
              index={i}
              onGenerateGuardRule={onGenerateGuardRule}
              generating={generatingName === p.name}
            />
          ))}
        </SpaceBetween>
      )}
    </SpaceBetween>
  );
}
