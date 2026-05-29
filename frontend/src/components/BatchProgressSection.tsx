import { useEffect, useState, useRef } from "react";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import ProgressBar from "@cloudscape-design/components/progress-bar";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Table from "@cloudscape-design/components/table";
import Box from "@cloudscape-design/components/box";
import SpaceBetween from "@cloudscape-design/components/space-between";

interface BatchProgressSectionProps {
  /** Names of the resources currently being analyzed, in submission order. */
  resourceNames: string[];
  /** True while the batch worker run is in flight. */
  analyzing: boolean;
}

/**
 * Live progress UI for the multi-resource batch flow.
 *
 * Mirrors the look-and-feel of `ProgressSection` (used by single-URL Quick
 * Scan): an elapsed-time counter, a progress bar, and a per-resource activity
 * table. The batch worker doesn't stream per-URL progress events back to the
 * frontend yet — instead we show every selected resource as "In progress" for
 * the duration of the run, which matches what's actually happening server-side
 * (the worker fans out all 5 quick scans in parallel under a single
 * ThreadPoolExecutor). When `analyzing` flips to false, the parent swaps this
 * out for `BatchResultsSection`, which has the per-resource cache + severity
 * details.
 */
export default function BatchProgressSection({
  resourceNames,
  analyzing,
}: BatchProgressSectionProps) {
  const [elapsed, setElapsed] = useState(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (analyzing) {
      setElapsed(0);
      intervalRef.current = setInterval(() => {
        setElapsed((prev) => prev + 1);
      }, 1000);
    }
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [analyzing]);

  const minutes = Math.floor(elapsed / 60);
  const seconds = elapsed % 60;
  const timeStr = `${minutes}:${seconds.toString().padStart(2, "0")}`;

  // Server-side fan-out is parallel, so wall-time tracks the slowest single
  // scan (~30-90 s on cold start). The progress bar caps at 95% while the run
  // is in flight to make it obvious we're still waiting on the response — the
  // parent unmounts this section the moment results arrive.
  const pct = Math.min(95, Math.floor((elapsed / 90) * 95));

  return (
    <Container
      header={
        <Header
          variant="h2"
          description={`Elapsed time: ${timeStr}  •  Running ${resourceNames.length} parallel scans`}
        >
          Batch Analysis Progress
        </Header>
      }
    >
      <SpaceBetween size="l">
        <ProgressBar
          value={pct}
          additionalInfo={
            analyzing
              ? "Cold-start agent + per-resource property enumeration. Cached resources return instantly; new ones take 30-90 s each."
              : "Finalizing results..."
          }
          status="in-progress"
        />

        <Table
          columnDefinitions={[
            {
              id: "name",
              header: "Resource",
              cell: (item: string) => item,
            },
            {
              id: "status",
              header: "Status",
              cell: () => (
                <StatusIndicator type="in-progress">In progress</StatusIndicator>
              ),
              width: 180,
            },
          ]}
          items={resourceNames}
          empty={
            <Box textAlign="center" color="inherit">
              No resources selected
            </Box>
          }
          variant="embedded"
        />
      </SpaceBetween>
    </Container>
  );
}
