import { describe, it, expect, vi } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import fc from "fast-check";
import ResourceSelector, {
  MAX_BATCH,
  computeSelectAll,
  isAnalyzeDisabled,
} from "./ResourceSelector";
import type { DiscoveredResource } from "../hooks/useDiscover";

/**
 * Arbitrary that generates a CFN-shaped resource type identifier paired with
 * a docs.aws.amazon.com URL. The URL itself doesn't matter for these tests —
 * only the ratio of selected vs available counts the component renders.
 */
const arbResource: fc.Arbitrary<DiscoveredResource> = fc
  .stringOf(fc.constantFrom(..."ABCDEFGHIJKLMNOPQRSTUVWXYZ"), {
    minLength: 1,
    maxLength: 8,
  })
  .map((suffix) => ({
    name: `AWS::Service::${suffix || "X"}`,
    url: `https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-${suffix.toLowerCase()}.html`,
  }));

describe("ResourceSelector — pure helpers", () => {
  /**
   * Property: max-batch enforcement.
   *
   * `isAnalyzeDisabled` must return true for any selection size > MAX_BATCH,
   * and for any size of 0, and false only for sizes in [1, MAX_BATCH] when
   * not already analyzing.
   */
  it("disables analyze when selectedCount > MAX_BATCH or === 0", () => {
    fc.assert(
      fc.property(fc.integer({ min: 0, max: 50 }), (n) => {
        const disabled = isAnalyzeDisabled(n, false);
        if (n === 0) expect(disabled).toBe(true);
        if (n > MAX_BATCH) expect(disabled).toBe(true);
        if (n > 0 && n <= MAX_BATCH) expect(disabled).toBe(false);
      }),
      { numRuns: 100 },
    );
  });

  it("disables analyze whenever the analyzing flag is set, regardless of count", () => {
    fc.assert(
      fc.property(fc.integer({ min: 0, max: 50 }), (n) => {
        expect(isAnalyzeDisabled(n, true)).toBe(true);
      }),
      { numRuns: 50 },
    );
  });

  /**
   * Property: select-all caps at MAX_BATCH.
   *
   * For any list of resources, `computeSelectAll` must return at most
   * MAX_BATCH names, and those names must be a prefix of the input list
   * (preserves the API's alphabetical sort).
   */
  it("computeSelectAll caps at MAX_BATCH and preserves input order", () => {
    fc.assert(
      fc.property(fc.array(arbResource, { minLength: 0, maxLength: 20 }), (resources) => {
        const result = computeSelectAll(resources);
        expect(result.length).toBeLessThanOrEqual(MAX_BATCH);
        expect(result.length).toBe(Math.min(resources.length, MAX_BATCH));
        // Names appear in the same order as the input.
        result.forEach((name, i) => {
          expect(name).toBe(resources[i].name);
        });
      }),
      { numRuns: 100 },
    );
  });
});

describe("ResourceSelector — component rendering", () => {
  it("shows the empty-state when no resources are passed", () => {
    const { container } = render(
      <ResourceSelector
        resources={[]}
        selectedNames={[]}
        onToggle={vi.fn()}
        onSelectAll={vi.fn()}
        onClearSelection={vi.fn()}
        onAnalyzeBatch={vi.fn()}
      />,
    );
    expect(container.textContent ?? "").toContain("No resources discovered");
  });

  it("renders the resource count and shows over-limit warning when selection exceeds MAX_BATCH", () => {
    const resources: DiscoveredResource[] = [
      { name: "AWS::S3::Bucket", url: "https://docs.aws.amazon.com/x/a.html" },
      { name: "AWS::S3::BucketPolicy", url: "https://docs.aws.amazon.com/x/b.html" },
      { name: "AWS::S3::AccessPoint", url: "https://docs.aws.amazon.com/x/c.html" },
      { name: "AWS::S3::MultiRegionAccessPoint", url: "https://docs.aws.amazon.com/x/d.html" },
      { name: "AWS::S3::StorageLens", url: "https://docs.aws.amazon.com/x/e.html" },
      { name: "AWS::S3::ObjectLambdaAccessPoint", url: "https://docs.aws.amazon.com/x/f.html" },
    ];

    // Simulate the parent claiming all 6 are selected (over limit by 1).
    const overLimitSelection = resources.map((r) => r.name);

    const { container } = render(
      <ResourceSelector
        resources={resources}
        selectedNames={overLimitSelection}
        onToggle={vi.fn()}
        onSelectAll={vi.fn()}
        onClearSelection={vi.fn()}
        onAnalyzeBatch={vi.fn()}
      />,
    );
    const text = container.textContent ?? "";
    // Counter shows total resources.
    expect(text).toContain("(6)");
    // Warning fires.
    expect(text).toContain(`Maximum ${MAX_BATCH}`);
    expect(text).toContain("Deselect 1");
  });

  it("invokes onAnalyzeBatch with the URLs of selected resources only", () => {
    const resources: DiscoveredResource[] = [
      { name: "AWS::S3::Bucket", url: "https://docs.aws.amazon.com/x/a.html" },
      { name: "AWS::S3::BucketPolicy", url: "https://docs.aws.amazon.com/x/b.html" },
    ];
    const onAnalyzeBatch = vi.fn();

    const { getByText } = render(
      <ResourceSelector
        resources={resources}
        selectedNames={["AWS::S3::Bucket"]}
        onToggle={vi.fn()}
        onSelectAll={vi.fn()}
        onClearSelection={vi.fn()}
        onAnalyzeBatch={onAnalyzeBatch}
      />,
    );
    fireEvent.click(getByText("Analyze 1 selected"));
    expect(onAnalyzeBatch).toHaveBeenCalledTimes(1);
    expect(onAnalyzeBatch).toHaveBeenCalledWith([
      "https://docs.aws.amazon.com/x/a.html",
    ]);
  });

  it("does not fire onAnalyzeBatch when no resources are selected", () => {
    const resources: DiscoveredResource[] = [
      { name: "AWS::S3::Bucket", url: "https://docs.aws.amazon.com/x/a.html" },
    ];
    const onAnalyzeBatch = vi.fn();

    const { getByText } = render(
      <ResourceSelector
        resources={resources}
        selectedNames={[]}
        onToggle={vi.fn()}
        onSelectAll={vi.fn()}
        onClearSelection={vi.fn()}
        onAnalyzeBatch={onAnalyzeBatch}
      />,
    );
    // Cloudscape disabled buttons do not fire onClick; the call count must remain 0.
    fireEvent.click(getByText("Analyze 0 selected"));
    expect(onAnalyzeBatch).not.toHaveBeenCalled();
  });
});
