# Implementation Plan: Analysis UX Improvements

## Overview

All changes are in `frontend/app.js`. We add a `parseNumberedList` utility, update `createPropertyCard` to accept an index and render lists, then wire the index through all rendering paths (batch and incremental).

## Tasks

- [x] 1. Implement `parseNumberedList` utility function
  - [x] 1.1 Add `parseNumberedList(text)` function to `frontend/app.js`
    - Splits text on `\d+\.\s` boundaries, returns `<ol>` with `<li>` items when 2+ items found, otherwise returns `<span>` with plain text
    - Returns empty string for null/undefined/empty input
    - _Requirements: 1.1, 1.2, 1.3, 1.4_
  - [x] 1.2 Write property test: Numbered text produces ordered list with correct item count
    - **Property 1: Numbered text produces ordered list with correct item count**
    - **Validates: Requirements 1.1, 1.2**
  - [x] 1.3 Write property test: Non-numbered text produces plain text
    - **Property 2: Non-numbered text produces plain text (no list)**
    - **Validates: Requirements 1.3**

- [x] 2. Update `createPropertyCard` for numbered lists and index prefix
  - [x] 2.1 Modify `createPropertyCard(property, index)` in `frontend/app.js`
    - Add optional `index` parameter; when provided, prefix title with `{index + 1}. `
    - Replace raw text interpolation in recommendation section with `parseNumberedList()` call
    - Add best practices section that renders `property.best_practices` using `parseNumberedList()` when present
    - Handle `best_practices` as array (join into numbered string) or string (pass directly)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.2_
  - [x] 2.2 Write property test: Property card title includes sequential number
    - **Property 3: Property card title includes sequential number**
    - **Validates: Requirements 2.2**

- [x] 3. Wire index through all rendering paths
  - [x] 3.1 Update `displayResults()` to pass index to `createPropertyCard`
    - Pass the `forEach` loop index as second argument to `createPropertyCard(normalized, index)`
    - _Requirements: 2.1, 2.2_
  - [x] 3.2 Update `displayQuickScanResults()` to pass index to `createPropertyCard`
    - Pass the `forEach` loop index as second argument to `createPropertyCard({...}, index)`
    - _Requirements: 2.1, 2.2_
  - [x] 3.3 Update `addPropertyCardToUI(property, index)` to accept and forward index
    - Add `index` parameter, pass to `createPropertyCard(property, index)`
    - _Requirements: 2.2, 2.3_
  - [x] 3.4 Update `handleStepPropertyAnalyzed(data)` to pass `detail.index` to `addPropertyCardToUI`
    - Extract index from `detail.index` and pass to `addPropertyCardToUI(property, index)`
    - _Requirements: 2.3_

- [x] 4. Checkpoint
  - Ensure all changes work together, ask the user if questions arise.

- [x] 5. Write unit tests for edge cases
  - [x] 5.1 Write unit tests for `parseNumberedList`
    - Test empty string, single sentence, two items, items with newlines, text with numbers that aren't list items (e.g., "There are 3 options")
    - _Requirements: 1.3, 1.4_
  - [x] 5.2 Write unit tests for `createPropertyCard` index rendering
    - Test with index=0, index=5, index=undefined to verify title prefix behavior
    - _Requirements: 2.2_

- [x] 6. Final checkpoint
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- All changes are in `frontend/app.js` — no backend or infrastructure changes needed
- Property tests use `fast-check` for JavaScript property-based testing
- The existing `normalizePropertyData()` already extracts `bestPractices` from agent responses
