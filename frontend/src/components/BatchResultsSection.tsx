import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import Badge from "@cloudscape-design/components/badge";
import Box from "@cloudscape-design/components/box";
import ExpandableSection from "@cloudscape-design/components/expandable-section";
import KeyValuePairs from "@cloudscape-design/components/key-value-pairs";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Alert from "@cloudscape-design/components/alert";
import type { BatchAnalysisResponse } from "../hooks/useAnalysis";
import type { PropertyData, RiskLevel } from "../types";
import PropertyCard from "./PropertyCard";

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

            return (
              <ExpandableSection
                key={key}
                headerText={key}
                headerCounter={`(${coercedProps.length})`}
                headerActions={
                  entry.cached ? (
                    <StatusIndicator type="info">
                      Cached{entry.cached_at ? ` (${entry.cached_at})` : ""}
                    </StatusIndicator>
                  ) : undefined
                }
              >
                {coercedProps.length === 0 ? (
                  <Box variant="p" color="inherit">
                    No properties returned for this resource.
                  </Box>
                ) : (
                  <SpaceBetween size="s">
                    {coercedProps.map((p, i) => (
                      <PropertyCard
                        key={`${key}-${p.name}-${i}`}
                        property={p}
                        index={i}
                      />
                    ))}
                  </SpaceBetween>
                )}
              </ExpandableSection>
            );
          })
        )}
      </SpaceBetween>
    </Container>
  );
}
