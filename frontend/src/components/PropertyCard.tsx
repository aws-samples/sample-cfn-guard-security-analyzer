import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import Badge from "@cloudscape-design/components/badge";
import Box from "@cloudscape-design/components/box";
import SpaceBetween from "@cloudscape-design/components/space-between";
import type { PropertyData, RiskLevel } from "../types";
import { parseNumberedList } from "../utils/parseNumberedList";

interface PropertyCardProps {
  property: PropertyData;
  index: number;
}

const RISK_BADGE_COLOR: Record<RiskLevel, "red" | "grey" | "blue" | "green"> = {
  CRITICAL: "red",
  HIGH: "red",
  MEDIUM: "blue",
  LOW: "green",
};

/**
 * Renders a single security property finding card.
 * Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5
 */
export default function PropertyCard({ property }: PropertyCardProps) {
  const badgeColor = RISK_BADGE_COLOR[property.risk_level] ?? "grey";

  const recommendation = property.recommendation
    ? parseNumberedList(property.recommendation)
    : null;

  return (
    <Container
      header={
        <Header
          variant="h3"
          actions={<Badge color={badgeColor}>{property.risk_level}</Badge>}
        >
          {property.name}
        </Header>
      }
    >
      <SpaceBetween size="s">
        {property.security_impact && (
          <div>
            <Box variant="awsui-key-label">Security Impact</Box>
            <Box>{property.security_impact}</Box>
          </div>
        )}

        {property.key_threat && (
          <div>
            <Box variant="awsui-key-label">Key Threat</Box>
            <Box color="text-status-error">{property.key_threat}</Box>
          </div>
        )}

        {recommendation && (
          <div>
            <Box variant="awsui-key-label">Recommendation</Box>
            {Array.isArray(recommendation) ? (
              <ol>
                {recommendation.map((item, i) => (
                  <li key={i}>{item}</li>
                ))}
              </ol>
            ) : (
              <Box>{recommendation}</Box>
            )}
          </div>
        )}
      </SpaceBetween>
    </Container>
  );
}
