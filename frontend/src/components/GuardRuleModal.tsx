import { useState } from "react";
import Modal from "@cloudscape-design/components/modal";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ExpandableSection from "@cloudscape-design/components/expandable-section";
import Badge from "@cloudscape-design/components/badge";
import type { GuardRule, RiskLevel } from "../types";

interface GuardRuleModalProps {
  rule: GuardRule | null;
  onDismiss: () => void;
  onAddToCollection: (rule: GuardRule) => void;
}

const BADGE_COLOR: Record<RiskLevel, "red" | "grey" | "blue" | "green"> = {
  CRITICAL: "red",
  HIGH: "red",
  MEDIUM: "blue",
  LOW: "green",
};

function CopyableCodeBlock({ code, label }: { code: string; label: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div>
      <Box variant="awsui-key-label">
        {label}
        <Button
          variant="inline-icon"
          iconName={copied ? "status-positive" : "copy"}
          onClick={handleCopy}
          ariaLabel={`Copy ${label}`}
        />
      </Box>
      <Box variant="code">
        <pre style={{ whiteSpace: "pre-wrap", margin: 0, fontSize: "13px" }}>
          {code}
        </pre>
      </Box>
    </div>
  );
}

export default function GuardRuleModal({
  rule,
  onDismiss,
  onAddToCollection,
}: GuardRuleModalProps) {
  if (!rule) return null;

  return (
    <Modal
      visible={!!rule}
      onDismiss={onDismiss}
      header={
        <SpaceBetween direction="horizontal" size="xs">
          <span>{rule.ruleName}</span>
          <Badge color={BADGE_COLOR[rule.riskLevel] ?? "grey"}>
            {rule.riskLevel}
          </Badge>
        </SpaceBetween>
      }
      footer={
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Box color="text-body-secondary" fontSize="body-s">
              Test with: <code>cfn-guard validate -r rules.guard -d template.yaml</code>
            </Box>
            <Button onClick={() => onAddToCollection(rule)}>
              Add to Collection
            </Button>
            <Button variant="primary" onClick={onDismiss}>
              Close
            </Button>
          </SpaceBetween>
        </Box>
      }
      size="large"
    >
      <SpaceBetween size="l">
        <Box>{rule.description}</Box>

        <CopyableCodeBlock code={rule.guardRule} label="Guard Rule" />

        <ExpandableSection headerText="Test Templates" variant="footer">
          <SpaceBetween size="m">
            <CopyableCodeBlock
              code={rule.passTemplate}
              label="Pass Template (secure configuration)"
            />
            <CopyableCodeBlock
              code={rule.failTemplate}
              label="Fail Template (insecure configuration)"
            />
          </SpaceBetween>
        </ExpandableSection>
      </SpaceBetween>
    </Modal>
  );
}
