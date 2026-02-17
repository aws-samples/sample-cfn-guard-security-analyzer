/**
 * @jest-environment jsdom
 */

// Feature: analysis-ux-improvements, Property 1: Numbered text produces ordered list with correct item count
// Validates: Requirements 1.1, 1.2

const fc = require('fast-check');
const { parseNumberedList } = require('../../frontend/app.js');

/**
 * Arbitrary that generates non-empty strings which do NOT contain
 * patterns like "2. " (digit-dot-space) that would cause extra splits
 * in the parseNumberedList regex.
 */
const safeItemText = fc
  .stringOf(
    fc.oneof(
      fc.constant('a'), fc.constant('b'), fc.constant('c'),
      fc.constant('x'), fc.constant('y'), fc.constant('z'),
      fc.constant('A'), fc.constant('B'), fc.constant('C'),
      fc.constant(' '), fc.constant(','), fc.constant('!'),
      fc.constant('-'), fc.constant('('), fc.constant(')'),
      fc.constant('_'), fc.constant(':'), fc.constant(';')
    ),
    { minLength: 1, maxLength: 40 }
  )
  .filter(s => {
    // Reject strings that contain digit-dot-space patterns (would cause extra splits)
    return !/\d+\.\s/.test(s) && s.trim().length > 0;
  });

/**
 * Arbitrary that generates arrays of 2-20 safe item strings,
 * then formats them as "1. item1 2. item2 ... N. itemN".
 */
const numberedListInput = fc
  .array(safeItemText, { minLength: 2, maxLength: 20 })
  .map(items => ({
    items,
    formatted: items.map((item, i) => `${i + 1}. ${item}`).join(' ')
  }));

describe('parseNumberedList - Property 1: Numbered text produces ordered list with correct item count', () => {
  it('should return exactly one <ol> with exactly N <li> elements for N numbered items (N >= 2)', () => {
    fc.assert(
      fc.property(numberedListInput, ({ items, formatted }) => {
        const result = parseNumberedList(formatted);

        // Exactly one <ol> element
        const olMatches = result.match(/<ol[^>]*>/g);
        expect(olMatches).not.toBeNull();
        expect(olMatches).toHaveLength(1);

        // Exactly one closing </ol>
        const olCloseMatches = result.match(/<\/ol>/g);
        expect(olCloseMatches).toHaveLength(1);

        // Exactly N <li> elements
        const liMatches = result.match(/<li>/g);
        expect(liMatches).not.toBeNull();
        expect(liMatches).toHaveLength(items.length);

        // Each <li> contains the corresponding item text without the number prefix
        items.forEach(item => {
          const trimmed = item.trim();
          expect(result).toContain(`<li>${trimmed}</li>`);
        });
      }),
      { numRuns: 100 }
    );
  });
});


// Feature: analysis-ux-improvements, Property 2: Non-numbered text produces plain text (no list)
// Validates: Requirements 1.3

/**
 * Arbitrary that generates strings which do NOT contain 2 or more
 * numbered item patterns (digit + dot + space). This means:
 * - Strings with zero occurrences of \d+\.\s are fine
 * - Strings with exactly one occurrence of \d+\.\s are fine
 * - Strings with 2+ occurrences are rejected
 *
 * Strategy: generate arbitrary strings and filter out those with 2+ matches.
 */
const nonNumberedText = fc
  .oneof(
    // Plain alphabetic/punctuation strings (no digits at all — guaranteed safe)
    fc.stringOf(
      fc.oneof(
        fc.constant('a'), fc.constant('b'), fc.constant('c'),
        fc.constant('M'), fc.constant('N'), fc.constant('O'),
        fc.constant(' '), fc.constant(','), fc.constant('.'),
        fc.constant('!'), fc.constant('?'), fc.constant('-'),
        fc.constant('('), fc.constant(')'), fc.constant(':')
      ),
      { minLength: 1, maxLength: 80 }
    ),
    // Strings that may contain digits but are filtered to have < 2 numbered patterns
    fc.string({ minLength: 1, maxLength: 80 }).filter(s => {
      const matches = s.match(/(?:^|\s)\d+\.\s/g);
      return (matches ? matches.length : 0) < 2;
    })
  )
  .filter(s => s.trim().length > 0);

describe('parseNumberedList - Property 2: Non-numbered text produces plain text (no list)', () => {
  it('should NOT return <ol> or <li> elements for text without 2+ numbered item patterns', () => {
    fc.assert(
      fc.property(nonNumberedText, (text) => {
        const result = parseNumberedList(text);

        // Output must not contain <ol> or <li> elements
        expect(result).not.toMatch(/<ol[\s>]/);
        expect(result).not.toMatch(/<\/ol>/);
        expect(result).not.toMatch(/<li>/);
        expect(result).not.toMatch(/<\/li>/);
      }),
      { numRuns: 100 }
    );
  });
});
