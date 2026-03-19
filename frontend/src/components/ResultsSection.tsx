import { useState } from "react";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import Badge from "@cloudscape-design/components/badge";
import Button from "@cloudscape-design/components/button";
import SegmentedControl from "@cloudscape-design/components/segmented-control";
import Grid from "@cloudscape-design/components/grid";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Box from "@cloudscape-design/components/box";
import KeyValuePairs from "@cloudscape-design/components/key-value-pairs";
import Tabs from "@cloudscape-design/components/tabs";
import Flashbar from "@cloudscape-design/components/flashbar";
import type { UseAnalysisReturn } from "../hooks/useAnalysis";
import type { PropertyData, RiskLevel } from "../types";
import { useGuardRules } from "../hooks/useGuardRules";
import PropertyCard from "./PropertyCard";
import GuardRuleModal from "./GuardRuleModal";
import GuardRulesTab from "./GuardRulesTab";
import { API_BASE_URL } from "../config";

interface ResultsSectionProps {
  analysis: UseAnalysisReturn;
}

type FilterLevel = "ALL" | RiskLevel;

/**
 * Compute severity counts from an array of PropertyData.
 * Exported for property-based testing.
 * Validates: Requirement 8.2
 */
export function computeSeverityCounts(
  results: PropertyData[],
): Record<RiskLevel, number> {
  const counts: Record<RiskLevel, number> = {
    CRITICAL: 0,
    HIGH: 0,
    MEDIUM: 0,
    LOW: 0,
  };
  for (const r of results) {
    if (r.risk_level in counts) {
      counts[r.risk_level]++;
    }
  }
  return counts;
}

/**
 * Filter properties by risk level. "ALL" returns all properties.
 * Exported for property-based testing.
 * Validates: Requirement 8.4
 */
export function filterByRiskLevel(
  results: PropertyData[],
  level: FilterLevel,
): PropertyData[] {
  if (level === "ALL") return results;
  return results.filter((r) => r.risk_level === level);
}

const BADGE_COLOR: Record<RiskLevel, "red" | "grey" | "blue" | "green"> = {
  CRITICAL: "red",
  HIGH: "red",
  MEDIUM: "blue",
  LOW: "green",
};

/**
 * Displays severity summary, risk level filter, property cards, and PDF report button.
 * Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 9.6
 */
export default function ResultsSection({ analysis }: ResultsSectionProps) {
  const [filterLevel, setFilterLevel] = useState<FilterLevel>("ALL");
  const [reportLoading, setReportLoading] = useState(false);
  const guardRules = useGuardRules();

  const handleGenerateGuardRule = (property: PropertyData) => {
    guardRules.generateRule(
      property,
      analysis.resourceUrl ?? "",
      analysis.resourceType ?? "",
    );
  };

  const counts = computeSeverityCounts(analysis.results);
  const filtered = filterByRiskLevel(analysis.results, filterLevel);

  const handleGenerateReport = async () => {
    if (!analysis.analysisId) return;
    setReportLoading(true);
    try {
      const response = await fetch(
        `${API_BASE_URL}/reports/${analysis.analysisId}`,
        { method: "POST" },
      );
      if (response.ok) {
        const data = await response.json();
        if (data.reportUrl) {
          window.open(data.reportUrl, "_blank");
        }
      }
    } finally {
      setReportLoading(false);
    }
  };

  return (
    <Container
      header={
        <Header
          variant="h2"
          actions={
            <Button
              onClick={handleGenerateReport}
              loading={reportLoading}
              disabled={!analysis.analysisId}
            >
              Generate PDF Report
            </Button>
          }
        >
          Analysis Results ({analysis.results.length} properties)
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
        <Tabs
          tabs={[
            {
              id: "results",
              label: `Analysis Results (${analysis.results.length})`,
              content: (
                <SpaceBetween size="l">
                  <KeyValuePairs
                    columns={4}
                    items={[
                      {
                        label: "Critical",
                        value: (
                          <Badge color={BADGE_COLOR.CRITICAL}>
                            {counts.CRITICAL}
                          </Badge>
                        ),
                      },
                      {
                        label: "High",
                        value: (
                          <Badge color={BADGE_COLOR.HIGH}>{counts.HIGH}</Badge>
                        ),
                      },
                      {
                        label: "Medium",
                        value: (
                          <Badge color={BADGE_COLOR.MEDIUM}>
                            {counts.MEDIUM}
                          </Badge>
                        ),
                      },
                      {
                        label: "Low",
                        value: (
                          <Badge color={BADGE_COLOR.LOW}>{counts.LOW}</Badge>
                        ),
                      },
                    ]}
                  />

                  <FormFieldFilter
                    filterLevel={filterLevel}
                    onFilterChange={setFilterLevel}
                  />

                  {filtered.length === 0 ? (
                    <Box textAlign="center" color="inherit" padding="l">
                      No properties match the selected filter.
                    </Box>
                  ) : (
                    <Grid
                      gridDefinition={filtered.map(() => ({
                        colspan: { default: 12, s: 6, l: 4 },
                      }))}
                    >
                      {filtered.map((property, index) => (
                        <PropertyCard
                          key={`${property.name}-${index}`}
                          property={property}
                          index={index}
                          generating={guardRules.generating === property.name}
                          onGenerateGuardRule={handleGenerateGuardRule}
                        />
                      ))}
                    </Grid>
                  )}
                </SpaceBetween>
              ),
            },
            ...(guardRules.rules.length > 0
              ? [{
                  id: "guard-rules",
                  label: `Guard Rules (${guardRules.rules.length})`,
                  content: (
                    <GuardRulesTab
                      rules={guardRules.rules}
                      onViewRule={guardRules.openModal}
                      onRemoveRule={guardRules.removeFromCollection}
                      onDownloadGuardFile={guardRules.downloadGuardFile}
                      onDownloadTestTemplates={guardRules.downloadTestTemplates}
                    />
                  ),
                }]
              : []),
          ]}
        />
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

function FormFieldFilter({
  filterLevel,
  onFilterChange,
}: {
  filterLevel: FilterLevel;
  onFilterChange: (level: FilterLevel) => void;
}) {
  return (
    <SegmentedControl
      selectedId={filterLevel}
      onChange={({ detail }) =>
        onFilterChange(detail.selectedId as FilterLevel)
      }
      options={[
        { id: "ALL", text: "All" },
        { id: "CRITICAL", text: "Critical" },
        { id: "HIGH", text: "High" },
        { id: "MEDIUM", text: "Medium" },
        { id: "LOW", text: "Low" },
      ]}
    />
  );
}
