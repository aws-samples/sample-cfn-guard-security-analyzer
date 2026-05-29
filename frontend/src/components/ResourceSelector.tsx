import { useCallback } from "react";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import Button from "@cloudscape-design/components/button";
import Cards from "@cloudscape-design/components/cards";
import Box from "@cloudscape-design/components/box";
import Alert from "@cloudscape-design/components/alert";
import Checkbox from "@cloudscape-design/components/checkbox";
import SpaceBetween from "@cloudscape-design/components/space-between";
import type { DiscoveredResource } from "../hooks/useDiscover";

/** Hard cap matches `MAX_URLS_PER_BATCH` in lambda/batch_handler.py. */
export const MAX_BATCH = 5;

interface ResourceSelectorProps {
  /** All resources surfaced by the discover step. */
  resources: DiscoveredResource[];
  /** Currently checked resource names (CFN type identifiers). */
  selectedNames: string[];
  /** Toggle handler called with the resource name being toggled. */
  onToggle: (name: string) => void;
  /** Replace the selection with all resources up to MAX_BATCH. */
  onSelectAll: () => void;
  /** Clear the selection. */
  onClearSelection: () => void;
  /** Submit the selected URLs to the batch endpoint. */
  onAnalyzeBatch: (urls: string[]) => void;
  /** True while a batch analysis is in flight; disables the submit button. */
  analyzing?: boolean;
}

/**
 * Compute whether the analyze button should be enabled.
 *
 * Pulled out as a pure helper so we can property-test it alongside the
 * max-batch enforcement. Disabled when:
 *   - selection is empty
 *   - selection exceeds MAX_BATCH
 *   - the analyze action is already in flight
 *
 * Exported for unit testing.
 */
export function isAnalyzeDisabled(
  selectedCount: number,
  analyzing: boolean,
): boolean {
  if (analyzing) return true;
  if (selectedCount === 0) return true;
  if (selectedCount > MAX_BATCH) return true;
  return false;
}

/**
 * Compute the next selection state after a "select all" action, capped at
 * MAX_BATCH. Exported for unit testing.
 *
 * If the discovered list has more than MAX_BATCH entries, we select the first
 * MAX_BATCH (sorted as the API returned them — alphabetical). The user can
 * then deselect and reselect within that window.
 */
export function computeSelectAll(
  resources: DiscoveredResource[],
): string[] {
  return resources.slice(0, MAX_BATCH).map((r) => r.name);
}

/**
 * Discovery + multi-select UI. Renders a Cloudscape `Cards` view of every
 * resource the discover endpoint returned, with per-card checkboxes, a
 * select-all / clear pair, and a primary "Analyze N selected" button.
 *
 * The component is presentational — selection state is owned by the parent so
 * it can be threaded into the same hook that drives the batch analysis call.
 */
export default function ResourceSelector({
  resources,
  selectedNames,
  onToggle,
  onSelectAll,
  onClearSelection,
  onAnalyzeBatch,
  analyzing = false,
}: ResourceSelectorProps) {
  const overLimit = selectedNames.length > MAX_BATCH;
  const submitDisabled = isAnalyzeDisabled(selectedNames.length, analyzing);

  const handleSubmit = useCallback(() => {
    if (submitDisabled) return;
    const selectedSet = new Set(selectedNames);
    const urls = resources
      .filter((r) => selectedSet.has(r.name))
      .map((r) => r.url);
    onAnalyzeBatch(urls);
  }, [resources, selectedNames, submitDisabled, onAnalyzeBatch]);

  if (resources.length === 0) {
    return (
      <Container header={<Header variant="h2">Discovered Resources</Header>}>
        <Box textAlign="center" color="inherit" padding="l">
          No resources discovered yet.
        </Box>
      </Container>
    );
  }

  return (
    <Container
      header={
        <Header
          variant="h2"
          counter={`(${resources.length})`}
          description={`Select up to ${MAX_BATCH} resources to analyze in parallel.`}
          actions={
            <SpaceBetween direction="horizontal" size="xs">
              <Button onClick={onSelectAll} disabled={analyzing}>
                Select All
              </Button>
              <Button onClick={onClearSelection} disabled={analyzing}>
                Clear
              </Button>
              <Button
                variant="primary"
                onClick={handleSubmit}
                disabled={submitDisabled}
                loading={analyzing}
              >
                Analyze {selectedNames.length} selected
              </Button>
            </SpaceBetween>
          }
        >
          Discovered Resources
        </Header>
      }
    >
      <SpaceBetween size="m">
        {overLimit && (
          <Alert
            type="warning"
            header={`Maximum ${MAX_BATCH} resources per batch`}
          >
            Deselect {selectedNames.length - MAX_BATCH} to continue.
          </Alert>
        )}
        <Cards
          items={resources}
          cardDefinition={{
            header: (item: DiscoveredResource) => (
              <Checkbox
                checked={selectedNames.includes(item.name)}
                onChange={() => onToggle(item.name)}
                disabled={analyzing}
              >
                {item.name}
              </Checkbox>
            ),
            sections: [
              {
                id: "url",
                content: (item: DiscoveredResource) => (
                  <Box variant="small" color="text-status-inactive">
                    {item.url}
                  </Box>
                ),
              },
            ],
          }}
          cardsPerRow={[{ cards: 1 }, { minWidth: 600, cards: 2 }]}
          trackBy="name"
          empty={
            <Box textAlign="center" color="inherit" padding="l">
              No resources discovered.
            </Box>
          }
        />
      </SpaceBetween>
    </Container>
  );
}
