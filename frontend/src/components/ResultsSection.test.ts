import { describe, it, expect } from "vitest";
import fc from "fast-check";
import { computeSeverityCounts, filterByRiskLevel } from "./ResultsSection";
import type { PropertyData, RiskLevel } from "../types";

const RISK_LEVELS: RiskLevel[] = ["CRITICAL", "HIGH", "MEDIUM", "LOW"];

/** Arbitrary that generates a valid PropertyData object with a random risk level. */
const arbPropertyData: fc.Arbitrary<PropertyData> = fc
  .record({
    name: fc.string({ minLength: 1 }),
    risk_level: fc.constantFrom(...RISK_LEVELS),
    description: fc.string(),
    security_impact: fc.string(),
    key_threat: fc.string(),
    secure_configuration: fc.string(),
    recommendation: fc.string(),
    property_path: fc.string(),
    best_practices: fc.array(fc.string()),
    common_misconfigurations: fc.array(fc.string()),
  });

/**
 * Property 5: Severity count accuracy
 * For any array of PropertyData objects, the severity summary counts
 * should equal the actual count of properties with each respective risk_level.
 *
 * **Validates: Requirements 8.2**
 */
describe("Property 5: Severity count accuracy", () => {
  it("computed counts match actual distribution for any PropertyData array", () => {
    fc.assert(
      fc.property(fc.array(arbPropertyData), (properties) => {
        const counts = computeSeverityCounts(properties);

        for (const level of RISK_LEVELS) {
          const actual = properties.filter((p) => p.risk_level === level).length;
          expect(counts[level]).toBe(actual);
        }
      }),
      { numRuns: 100 },
    );
  });

  it("total of all counts equals array length", () => {
    fc.assert(
      fc.property(fc.array(arbPropertyData), (properties) => {
        const counts = computeSeverityCounts(properties);
        const total = counts.CRITICAL + counts.HIGH + counts.MEDIUM + counts.LOW;
        expect(total).toBe(properties.length);
      }),
      { numRuns: 100 },
    );
  });
});

/**
 * Property 6: Risk level filtering
 * For any array of PropertyData objects and any selected risk level filter,
 * the filtered result should contain exactly the properties matching that risk level,
 * or all properties when "All" is selected.
 *
 * **Validates: Requirements 8.4**
 */
describe("Property 6: Risk level filtering", () => {
  it("ALL filter returns all properties", () => {
    fc.assert(
      fc.property(fc.array(arbPropertyData), (properties) => {
        const filtered = filterByRiskLevel(properties, "ALL");
        expect(filtered).toEqual(properties);
      }),
      { numRuns: 100 },
    );
  });

  it("specific risk level filter returns only matching properties", () => {
    fc.assert(
      fc.property(
        fc.array(arbPropertyData),
        fc.constantFrom(...RISK_LEVELS),
        (properties, level) => {
          const filtered = filterByRiskLevel(properties, level);
          // Every item in filtered must have the selected risk level
          for (const item of filtered) {
            expect(item.risk_level).toBe(level);
          }
          // Count must match manual filter
          const expected = properties.filter((p) => p.risk_level === level);
          expect(filtered.length).toBe(expected.length);
        },
      ),
      { numRuns: 100 },
    );
  });
});
