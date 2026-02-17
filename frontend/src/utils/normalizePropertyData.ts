import type { PropertyData } from "../types";

/**
 * Raw property data from any API format — loosely typed to accept
 * DynamoDB Payload wrappers, WebSocket result wrappers, direct objects,
 * and text with embedded JSON.
 *
 * Validates: Requirements 10.1, 10.2, 10.3
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type RawPropertyData = Record<string, any>;

/**
 * Extract the first balanced JSON object from a text string.
 * Tracks brace depth to find the matching closing brace.
 */
function extractJsonFromText(text: string): RawPropertyData | null {
  const startIdx = text.indexOf("{");
  if (startIdx === -1) return null;

  let depth = 0;
  let endIdx = -1;
  for (let i = startIdx; i < text.length; i++) {
    if (text[i] === "{") depth++;
    else if (text[i] === "}") {
      depth--;
      if (depth === 0) {
        endIdx = i;
        break;
      }
    }
  }

  if (endIdx === -1) return null;

  try {
    return JSON.parse(text.substring(startIdx, endIdx + 1));
  } catch {
    return null;
  }
}

/**
 * Normalize a raw property object from any known API format into a
 * consistent PropertyData shape.
 *
 * Supported formats:
 * - Already normalized (has `name` and `risk_level` at top level)
 * - DynamoDB Map output: `{ property: {...}, propertyResult: { Payload: {...} } }`
 * - WebSocket message: `{ result: { statusCode, result: "<text with JSON>" } }`
 * - Direct Payload wrapper: `{ Payload: {...} }`
 * - String payload with embedded JSON
 */
export function normalizePropertyData(raw: RawPropertyData): PropertyData {
  // Already normalized — pass through
  if (raw.name && raw.risk_level) return raw as PropertyData;

  // Extract property metadata (from crawler)
  const propMeta: RawPropertyData = raw.property || {};

  // Extract analysis payload from the various wrapper formats
  const analysisPayload: unknown =
    raw.propertyResult?.Payload || raw.result || raw.Payload || {};

  let analysis: RawPropertyData = {};

  if (typeof analysisPayload === "string") {
    // Raw string — try to extract JSON
    const extracted = extractJsonFromText(analysisPayload);
    if (extracted) analysis = extracted;
  } else if (
    typeof analysisPayload === "object" &&
    analysisPayload !== null &&
    !(analysisPayload as RawPropertyData).error
  ) {
    const payload = analysisPayload as RawPropertyData;
    const resultText: unknown = payload.result ?? "";

    if (typeof resultText === "string" && resultText.length > 0) {
      // Text with embedded JSON — extract balanced object
      const extracted = extractJsonFromText(resultText);
      if (extracted) analysis = extracted;
    } else if (typeof resultText === "object" && resultText !== null) {
      analysis = resultText as RawPropertyData;
    }
  }

  return {
    name:
      analysis.propertyName ||
      analysis.name ||
      propMeta.name ||
      raw.name ||
      "Unknown Property",
    risk_level:
      analysis.riskLevel ||
      analysis.risk_level ||
      propMeta.risk_level ||
      "MEDIUM",
    description: analysis.description || propMeta.description || "",
    security_impact:
      analysis.securityImplications ||
      analysis.security_impact ||
      analysis.securityImplication ||
      propMeta.description ||
      "",
    key_threat:
      analysis.key_threat ||
      (analysis.commonMisconfigurations
        ? analysis.commonMisconfigurations[0]
        : "") ||
      "",
    secure_configuration:
      analysis.secure_configuration ||
      analysis.recommendations ||
      analysis.recommendation ||
      "",
    recommendation:
      analysis.recommendations ||
      analysis.recommendation ||
      analysis.secure_configuration ||
      "",
    property_path: propMeta.name || raw.name || "",
    best_practices: analysis.bestPractices || [],
    common_misconfigurations: analysis.commonMisconfigurations || [],
  };
}
