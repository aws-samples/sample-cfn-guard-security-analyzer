/**
 * @jest-environment jsdom
 */

// Unit tests for createPropertyCard index rendering
// Validates: Requirements 2.2

const { createPropertyCard } = require('../../frontend/app.js');

describe('createPropertyCard - index rendering', () => {
  const baseProperty = {
    name: 'AccessControl',
    risk_level: 'HIGH',
    security_impact: 'Unauthorized access possible',
  };

  function getTitleText(card) {
    const h4 = card.querySelector('h4.text-lg.font-bold.text-gray-900');
    expect(h4).not.toBeNull();
    return h4.textContent;
  }

  it('prefixes title with "1. " when index is 0', () => {
    const card = createPropertyCard(baseProperty, 0);
    expect(getTitleText(card)).toBe('1. AccessControl');
  });

  it('prefixes title with "6. " when index is 5', () => {
    const card = createPropertyCard(baseProperty, 5);
    expect(getTitleText(card)).toBe('6. AccessControl');
  });

  it('renders title without number prefix when index is undefined', () => {
    const card = createPropertyCard(baseProperty);
    expect(getTitleText(card)).toBe('AccessControl');
  });
});
