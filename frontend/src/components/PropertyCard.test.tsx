import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import fc from "fast-check";
import PropertyCard from "./PropertyCard";
import type { PropertyData, RiskLevel } from "../types";

const RISK_LEVELS: RiskLevel[] = ["CRITICAL", "HIGH", "MEDIUM", "LOW"];

/**
 * Arbitrary that generates printable, non-whitespace-only strings.
 * This avoids testing-library normalization issues with whitespace-only text.
 */
const arbVisibleString = (opts?: { minLength?: number; maxLength?: number }) =>
  fc
    .stringOf(
      fc.char().filter((c) => c.trim().length > 0 && c !== "<" && c !== ">"),
      { minLength: opts?.minLength ?? 1, maxLength: opts?.maxLength ?? 40 },
    )
    .filter((s) => s.trim().length > 0);

/** Arbitrary that generates a valid PropertyData object with visible text. */
const arbPropertyData: fc.Arbitrary<PropertyData> = fc.record({
  name: arbVisibleString({ minLength: 2 }),
  risk_level: fc.constantFrom(...RISK_LEVELS),
  description: arbVisibleString(),
  security_impact: arbVisibleString({ minLength: 2 }),
  key_threat: fc.oneof(fc.constant(""), arbVisibleString()),
  secure_configuration: fc.string(),
  recommendation: fc.oneof(fc.constant(""), arbVisibleString()),
  property_path: fc.string(),
  best_practices: fc.array(fc.string()),
  common_misconfigurations: fc.array(fc.string()),
});

/**
 * Property 7: PropertyCard field rendering
 * For any PropertyData object, the rendered PropertyCard should display
 * the property name, a Badge with the correct risk level, and the security_impact text.
 * When key_threat is non-empty, it should appear in the rendered output.
 * When recommendation is non-empty, it should appear in the rendered output.
 *
 * **Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5**
 */
describe("Property 7: PropertyCard field rendering", () => {
  it("renders property name, risk level badge, and security impact", () => {
    fc.assert(
      fc.property(arbPropertyData, (property) => {
        const { unmount, container } = render(
          <PropertyCard property={property} index={0} />,
        );
        const text = container.textContent ?? "";

        // 9.1: Property name displayed
        expect(text).toContain(property.name);

        // 9.2: Risk level badge displayed
        expect(text).toContain(property.risk_level);

        // 9.3: Security impact displayed
        expect(text).toContain(property.security_impact);

        unmount();
      }),
      { numRuns: 100 },
    );
  });

  it("renders key_threat when present, omits when empty", () => {
    fc.assert(
      fc.property(arbPropertyData, (property) => {
        const { unmount, container } = render(
          <PropertyCard property={property} index={0} />,
        );
        const text = container.textContent ?? "";

        if (property.key_threat) {
          // 9.4: Key threat displayed when present
          expect(text).toContain(property.key_threat);
          expect(text).toContain("Key Threat");
        } else {
          // Key Threat label should not appear when empty
          expect(text).not.toContain("Key Threat");
        }

        unmount();
      }),
      { numRuns: 100 },
    );
  });

  it("renders recommendation when present, omits when empty", () => {
    fc.assert(
      fc.property(arbPropertyData, (property) => {
        const { unmount, container } = render(
          <PropertyCard property={property} index={0} />,
        );
        const text = container.textContent ?? "";

        if (property.recommendation) {
          // 9.5: Recommendation displayed when present
          expect(text).toContain("Recommendation");
        } else {
          expect(text).not.toContain("Recommendation");
        }

        unmount();
      }),
      { numRuns: 100 },
    );
  });
});
