/**
 * @jest-environment jsdom
 */

// Unit tests for parseNumberedList
// Validates: Requirements 1.3, 1.4

const { parseNumberedList } = require('../../frontend/app.js');

describe('parseNumberedList - unit tests', () => {
  // Requirement 1.4: empty/absent text returns empty string
  it('returns empty string for empty string input', () => {
    expect(parseNumberedList('')).toBe('');
  });

  it('returns empty string for null input', () => {
    expect(parseNumberedList(null)).toBe('');
  });

  it('returns empty string for undefined input', () => {
    expect(parseNumberedList(undefined)).toBe('');
  });

  // Requirement 1.3: non-numbered text renders as plain text
  it('returns <span> for a single sentence without numbers', () => {
    const text = 'Enable encryption at rest';
    const result = parseNumberedList(text);
    expect(result).toBe(`<span>${text}</span>`);
  });

  // Requirement 1.1/1.2: numbered items render as <ol>
  it('returns <ol> with 2 <li> for two inline numbered items', () => {
    const text = '1. Enable encryption 2. Use KMS keys';
    const result = parseNumberedList(text);
    expect(result).toContain('<ol');
    expect(result).toContain('<li>Enable encryption</li>');
    expect(result).toContain('<li>Use KMS keys</li>');
    const liCount = (result.match(/<li>/g) || []).length;
    expect(liCount).toBe(2);
  });

  it('returns <ol> with 2 <li> for newline-separated numbered items', () => {
    const text = '1. First item\n2. Second item';
    const result = parseNumberedList(text);
    expect(result).toContain('<ol');
    expect(result).toContain('<li>First item</li>');
    expect(result).toContain('<li>Second item</li>');
    const liCount = (result.match(/<li>/g) || []).length;
    expect(liCount).toBe(2);
  });

  // Requirement 1.3: text with numbers that aren't list items
  it('returns <span> for text with numbers that are not list items', () => {
    const text = 'There are 3 options available';
    const result = parseNumberedList(text);
    expect(result).toBe(`<span>${text}</span>`);
    expect(result).not.toContain('<ol');
    expect(result).not.toContain('<li>');
  });

  // Edge case: single numbered item is not enough for a list
  it('returns <span> for a single numbered item', () => {
    const text = '1. Only one item';
    const result = parseNumberedList(text);
    expect(result).toBe(`<span>${text}</span>`);
    expect(result).not.toContain('<ol');
    expect(result).not.toContain('<li>');
  });
});
