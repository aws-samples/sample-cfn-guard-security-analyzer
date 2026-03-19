import { useState } from "react";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import Button from "@cloudscape-design/components/button";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Badge from "@cloudscape-design/components/badge";
import Box from "@cloudscape-design/components/box";
import type { GuardRule, RiskLevel } from "../types";

interface GuardRulesTabProps {
  rules: GuardRule[];
  onViewRule: (rule: GuardRule) => void;
  onRemoveRule: (ruleName: string) => void;
  onDownloadGuardFile: () => void;
  onDownloadTestTemplates: () => void;
}

const BADGE_COLOR: Record<RiskLevel, "red" | "grey" | "blue" | "green"> = {
  CRITICAL: "red",
  HIGH: "red",
  MEDIUM: "blue",
  LOW: "green",
};

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <Button
      iconName={copied ? "status-positive" : "copy"}
      onClick={handleCopy}
      ariaLabel="Copy rule"
    >
      {copied ? "Copied" : "Copy"}
    </Button>
  );
}

export default function GuardRulesTab({
  rules,
  onViewRule,
  onRemoveRule,
  onDownloadGuardFile,
  onDownloadTestTemplates,
}: GuardRulesTabProps) {
  if (rules.length === 0) {
    return (
      <Box textAlign="center" color="inherit" padding="l">
        No guard rules generated yet. Click "Generate Guard Rule" on a property
        card to get started.
      </Box>
    );
  }

  return (
    <SpaceBetween size="l">
      {rules.map((rule) => (
        <Container
          key={rule.ruleName}
          header={
            <Header
              variant="h3"
              actions={
                <SpaceBetween direction="horizontal" size="xs">
                  <Button onClick={() => onViewRule(rule)}>View Rule</Button>
                  <CopyButton text={rule.guardRule} />
                  <Button
                    variant="icon"
                    iconName="remove"
                    onClick={() => onRemoveRule(rule.ruleName)}
                    ariaLabel={`Remove ${rule.ruleName}`}
                  />
                </SpaceBetween>
              }
            >
              <SpaceBetween direction="horizontal" size="xs">
                <span>{rule.ruleName}</span>
                <Badge color={BADGE_COLOR[rule.riskLevel] ?? "grey"}>
                  {rule.riskLevel}
                </Badge>
              </SpaceBetween>
            </Header>
          }
        >
          <Box color="text-body-secondary">{rule.description}</Box>
        </Container>
      ))}

      <Box float="right">
        <SpaceBetween direction="horizontal" size="xs">
          <Button iconName="download" onClick={onDownloadGuardFile}>
            Download All as .guard File
          </Button>
          <Button iconName="download" onClick={onDownloadTestTemplates}>
            Download Test Templates (.yaml)
          </Button>
        </SpaceBetween>
      </Box>
    </SpaceBetween>
  );
}
