/**
 * @jest-environment jsdom
 */

// Feature: analysis-ux-improvements, Property 3: Property card title includes sequential number
// Validates: Requirements 2.2

const fc = require('fast-check');
const { createPropertyCard } = require('../../frontend/app.js');

/**
 * Arbitrary that generates property name strings that do NOT contain
 * digit-dot-space patterns (to avoid confusion with the numbering prefix).
 */
const safePropertyName = fc
  .stringOf(
    fc.oneof(
      fc.constant('a'), fc.constant('b'), fc.constant('c'),
      fc.constant('d'), fc.constant('e'), fc.constant('f'),
      fc.constant('A'), fc.constant('B'), fc.constant('C'),
      fc.constant('X'), fc.constant('Y'), fc.constant('Z'),
      fc.constant('_'), fc.constant('-'), fc.constant(':')
    ),
    { minLength: 1, maxLength: 40 }
  )
  .filter(s => !/\d+\.\s/.test(s) && s.trim().length > 0);

/**
 * Arbitrary that generates a property object with a random name
 * and optional risk_level.
 */
const propertyArb = safePropertyName.map(name => ({
  name,
  risk_level: fc.sample(fc.constantFrom('CRITICAL', 'HIGH', 'MEDIUM', 'LOW'), 1)[0]
}));

/**
 * Arbitrary for non-negative integer indices (0-based).
 */
const indexArb = fc.nat({ max: 999 });

describe('createPropertyCard - Property 3: Property card title includes sequential number', () => {
  it('should produce a card title starting with "{index + 1}. " followed by the property name', () => {
    fc.assert(
      fc.property(propertyArb, indexArb, (property, index) => {
        const card = createPropertyCard(property, index);

        // Find the h4 title element
        const h4 = card.querySelector('h4.text-lg.font-bold.text-gray-900');
        expect(h4).not.toBeNull();

        const expectedPrefix = `${index + 1}. `;
        const titleText = h4.textContent;

        // Title must start with the sequential number prefix
        expect(titleText.startsWith(expectedPrefix)).toBe(true);

        // Title must contain the property name after the prefix
        expect(titleText).toBe(`${expectedPrefix}${property.name}`);
      }),
      { numRuns: 100 }
    );
  });
});
