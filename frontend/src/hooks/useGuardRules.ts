import { useState, useCallback } from "react";
import type { GuardRule, PropertyData } from "../types";
import { API_BASE_URL } from "../config";
import { pollUntilDone, PollTimeoutError } from "../utils/poll";

export interface UseGuardRulesReturn {
  rules: GuardRule[];
  generating: string | null;
  modalRule: GuardRule | null;
  error: string | null;
  generateRule: (
    property: PropertyData,
    resourceUrl: string,
    resourceType: string,
  ) => Promise<void>;
  addToCollection: (rule: GuardRule) => void;
  removeFromCollection: (ruleName: string) => void;
  openModal: (rule: GuardRule) => void;
  closeModal: () => void;
  clearError: () => void;
  downloadGuardFile: () => void;
  downloadTestTemplates: () => void;
}

function triggerDownload(content: string, filename: string) {
  const blob = new Blob([content], { type: "text/plain" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/** Indent each line of a multi-line string by `spaces` spaces. */
function indent(text: string, spaces: number): string {
  const pad = " ".repeat(spaces);
  return text
    .split("\n")
    .map((line) => pad + line)
    .join("\n");
}

export function useGuardRules(): UseGuardRulesReturn {
  const [rulesMap, setRulesMap] = useState<Map<string, GuardRule>>(new Map());
  const [generating, setGenerating] = useState<string | null>(null);
  const [modalRule, setModalRule] = useState<GuardRule | null>(null);
  const [error, setError] = useState<string | null>(null);

  const rules = Array.from(rulesMap.values());

  const generateRule = useCallback(
    async (property: PropertyData, resourceUrl: string, resourceType: string) => {
      setGenerating(property.name);
      setError(null);

      // Phase 8 async pattern: POST returns 202 + ruleId, frontend polls
      // GET /guard-rules/{ruleId}. Up to 5 min total to absorb cold-start
      // guard rule generation + cfn-guard self-validation tool calls.
      try {
        const resp = await fetch(`${API_BASE_URL}/guard-rules`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            resourceType,
            resourceUrl,
            propertyName: property.name,
            riskLevel: property.risk_level,
            securityImplication: property.security_impact,
            recommendation: property.recommendation,
          }),
        });

        if (!resp.ok && resp.status !== 202) {
          const detail = await resp.json().catch(() => ({}));
          throw new Error(detail.error || detail.detail || `HTTP ${resp.status}`);
        }

        const dispatched = await resp.json();
        const ruleId: string | undefined = dispatched.ruleId;

        // Backwards-compat path: if the backend ever returns inline data, use it.
        if (!ruleId && dispatched.guardRule) {
          const rule: GuardRule = { ...dispatched, riskLevel: property.risk_level };
          setModalRule(rule);
          return;
        }
        if (!ruleId) {
          throw new Error("No ruleId returned from server");
        }

        type GuardRuleJob = {
          status: string;
          result?: GuardRule;
          error?: string;
        };
        const finalState = await pollUntilDone<GuardRuleJob>(
          `${API_BASE_URL}/guard-rules/${ruleId}`,
          (d) => d.status === "COMPLETED" || d.status === "FAILED",
        );

        if (finalState.status === "FAILED") {
          throw new Error(finalState.error || "Guard rule generation failed");
        }
        if (!finalState.result) {
          throw new Error("Guard rule completed but no result was returned");
        }
        const rule: GuardRule = {
          ...finalState.result,
          riskLevel: property.risk_level,
        };
        setModalRule(rule);
      } catch (err: unknown) {
        const msg =
          err instanceof PollTimeoutError
            ? "Guard rule generation timed out after 5 minutes"
            : (err as Error).message;
        setError(msg);
      } finally {
        setGenerating(null);
      }
    },
    [],
  );

  const addToCollection = useCallback((rule: GuardRule) => {
    setRulesMap((prev) => new Map(prev).set(rule.propertyName, rule));
  }, []);

  const removeFromCollection = useCallback((ruleName: string) => {
    setRulesMap((prev) => {
      const next = new Map(prev);
      for (const [key, val] of next) {
        if (val.ruleName === ruleName) {
          next.delete(key);
          break;
        }
      }
      return next;
    });
  }, []);

  const openModal = useCallback((rule: GuardRule) => setModalRule(rule), []);
  const closeModal = useCallback(() => setModalRule(null), []);
  const clearError = useCallback(() => setError(null), []);

  const downloadGuardFile = useCallback(() => {
    if (rules.length === 0) return;
    const timestamp = new Date().toISOString();
    const resourceType = rules[0]?.resourceType ?? "Unknown";
    const header = `# ============================================================\n# CFN Guard Rules — Generated by CloudFormation Security Analyzer\n# Resource: ${resourceType}\n# Generated: ${timestamp}\n# ============================================================\n`;
    const body = rules
      .map(
        (r) =>
          `\n# Rule: ${r.ruleName}\n# Risk: ${r.riskLevel}\n# Description: ${r.description}\n${r.guardRule}\n`,
      )
      .join("\n");
    triggerDownload(header + body, "cfn-guard-rules.guard");
  }, [rules]);

  const downloadTestTemplates = useCallback(() => {
    if (rules.length === 0) return;
    const entries = rules.flatMap((r) => [
      `- name: "${r.ruleName} - PASS"\n  input:\n${indent(r.passTemplate, 4)}\n  expectations:\n    rules:\n      ${r.ruleName}: PASS\n`,
      `- name: "${r.ruleName} - FAIL"\n  input:\n${indent(r.failTemplate, 4)}\n  expectations:\n    rules:\n      ${r.ruleName}: FAIL\n`,
    ]);
    triggerDownload(entries.join("\n"), "cfn-guard-tests.yaml");
  }, [rules]);

  return {
    rules,
    generating,
    modalRule,
    error,
    generateRule,
    addToCollection,
    removeFromCollection,
    openModal,
    closeModal,
    clearError,
    downloadGuardFile,
    downloadTestTemplates,
  };
}
