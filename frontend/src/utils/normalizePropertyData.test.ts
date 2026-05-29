import { describe, it, expect } from "vitest";
import fc from "fast-check";
import { normalizePropertyData } from "./normalizePropertyData";
import type { PropertyData, RiskLevel } from "../types";

const RISK_LEVELS: RiskLevel[] = ["CRITICAL", "HIGH", "MEDIUM", "LOW"];

/** Arbitrary for a valid risk level string. */
const arbRiskLevel = fc.constantFrom(...RISK_LEVELS);

/**
 * Arbitrary for a safe non-empty alphanumeric-ish string that won't break
 * JSON embedding. Uses only letters, digits, spaces, and basic punctuation.
 */
const arbSafeString = fc
  .stringOf(fc.constantFrom(..."abcdefghijklmnopqrstuvwxyz0123456789 _-,.!"), {
    minLength: 1,
    maxLength: 40,
  })
  .filter((s) => s.trim().length > 0)
  .map((s) => s.trim());

/** Arbitrary for a fully-formed PropertyData object. */
const arbPropertyData: fc.Arbitrary<PropertyData> = fc.record({
  name: arbSafeString,
  risk_level: arbRiskLevel,
  description: fc.string(),
  security_impact: fc.string(),
  key_threat: fc.string(),
  secure_configuration: fc.string(),
  recommendation: fc.string(),
  property_path: fc.string(),
  best_practices: fc.array(fc.string(), { maxLength: 3 }),
  common_misconfigurations: fc.array(fc.string(), { maxLength: 3 }),
});

/**
 * Wrap a property analysis object in a DynamoDB Payload wrapper format.
 */
function wrapAsDynamoDB(name: string, riskLevel: string, securityImpact: string, recommendation: string) {
  const innerJson = JSON.stringify({
    propertyName: name,
    riskLevel,
    securityImplications: securityImpact,
    recommendations: recommendation,
  });
  return {
    property: { name, description: "test desc" },
    propertyResult: {
      Payload: {
        statusCode: 200,
        result: `Here is the analysis: ${innerJson} end of analysis`,
      },
    },
  };
}

/**
 * Wrap as a WebSocket result wrapper.
 */
function wrapAsWebSocket(name: string, riskLevel: string, securityImpact: string, recommendation: string) {
  const innerJson = JSON.stringify({
    propertyName: name,
    riskLevel,
    securityImplications: securityImpact,
    recommendations: recommendation,
  });
  return {
    result: {
      statusCode: 200,
      result: `Analysis result: ${innerJson}`,
    },
  };
}

/**
 * Wrap as a direct object with name and risk_level at top level.
 */
function wrapAsDirect(name: string, riskLevel: string, securityImpact: string, recommendation: string) {
  return {
    name,
    risk_level: riskLevel,
    security_impact: securityImpact,
    recommendation,
  };
}

/**
 * Wrap as a raw string payload with embedded JSON.
 */
function wrapAsStringPayload(name: string, riskLevel: string, securityImpact: string, recommendation: string) {
  const innerJson = JSON.stringify({
    propertyName: name,
    riskLevel,
    securityImplications: securityImpact,
    recommendations: recommendation,
  });
  return {
    Payload: innerJson,
  };
}

describe("normalizePropertyData — Property Tests", () => {
  /**
   * Property 8: Normalizer format handling
   *
   * For any raw property object in any of the known API formats
   * (DynamoDB Payload wrapper, WebSocket result wrapper, direct object,
   * or text with embedded JSON), normalizePropertyData should return an
   * object with all required PropertyData fields populated from the input data.
   *
   * **Validates: Requirements 10.1, 10.2**
   */
  it("Property 8: normalized output has all required fields for DynamoDB Payload wrapper", () => {
    fc.assert(
      fc.property(
        arbSafeString,
        arbRiskLevel,
        arbSafeString,
        arbSafeString,
        (name, riskLevel, impact, rec) => {
          const raw = wrapAsDynamoDB(name, riskLevel, impact, rec);
          const result = normalizePropertyData(raw);

          expect(result).toHaveProperty("name");
          expect(result).toHaveProperty("risk_level");
          expect(result).toHaveProperty("security_impact");
          expect(result).toHaveProperty("recommendation");
          expect(result.name).toBe(name);
          expect(result.risk_level).toBe(riskLevel);
        },
      ),
      { numRuns: 100 },
    );
  });

  it("Property 8: normalized output has all required fields for WebSocket result wrapper", () => {
    fc.assert(
      fc.property(
        arbSafeString,
        arbRiskLevel,
        arbSafeString,
        arbSafeString,
        (name, riskLevel, impact, rec) => {
          const raw = wrapAsWebSocket(name, riskLevel, impact, rec);
          const result = normalizePropertyData(raw);

          expect(result).toHaveProperty("name");
          expect(result).toHaveProperty("risk_level");
          expect(result).toHaveProperty("security_impact");
          expect(result).toHaveProperty("recommendation");
          expect(result.name).toBe(name);
          expect(result.risk_level).toBe(riskLevel);
        },
      ),
      { numRuns: 100 },
    );
  });

  it("Property 8: normalized output has all required fields for direct object", () => {
    fc.assert(
      fc.property(
        arbSafeString,
        arbRiskLevel,
        arbSafeString,
        arbSafeString,
        (name, riskLevel, impact, rec) => {
          const raw = wrapAsDirect(name, riskLevel, impact, rec);
          const result = normalizePropertyData(raw);

          expect(result).toHaveProperty("name");
          expect(result).toHaveProperty("risk_level");
          expect(result).toHaveProperty("security_impact");
          expect(result).toHaveProperty("recommendation");
          expect(result.name).toBe(name);
          expect(result.risk_level).toBe(riskLevel);
        },
      ),
      { numRuns: 100 },
    );
  });

  it("Property 8: normalized output has all required fields for string Payload with embedded JSON", () => {
    fc.assert(
      fc.property(
        arbSafeString,
        arbRiskLevel,
        arbSafeString,
        arbSafeString,
        (name, riskLevel, impact, rec) => {
          const raw = wrapAsStringPayload(name, riskLevel, impact, rec);
          const result = normalizePropertyData(raw);

          expect(result).toHaveProperty("name");
          expect(result).toHaveProperty("risk_level");
          expect(result).toHaveProperty("security_impact");
          expect(result).toHaveProperty("recommendation");
          expect(result.name).toBe(name);
          expect(result.risk_level).toBe(riskLevel);
        },
      ),
      { numRuns: 100 },
    );
  });

  /**
   * Property 9: Normalizer idempotence
   *
   * For any PropertyData object that is already normalized,
   * calling normalizePropertyData should return an equivalent object —
   * i.e., normalizePropertyData(normalizePropertyData(x)) equals
   * normalizePropertyData(x).
   *
   * **Validates: Requirements 10.3**
   */
  it("Property 9: normalizePropertyData is idempotent", () => {
    fc.assert(
      fc.property(arbPropertyData, (propData) => {
        const once = normalizePropertyData(propData);
        const twice = normalizePropertyData(once);

        expect(twice).toEqual(once);
      }),
      { numRuns: 100 },
    );
  });
});
