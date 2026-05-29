import { useEffect, useState, useRef } from "react";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import ProgressBar from "@cloudscape-design/components/progress-bar";
import Table from "@cloudscape-design/components/table";
import Box from "@cloudscape-design/components/box";
import SpaceBetween from "@cloudscape-design/components/space-between";
import type { UseAnalysisReturn } from "../hooks/useAnalysis";

interface ProgressSectionProps {
  analysis: UseAnalysisReturn;
}

/**
 * Displays analysis progress bar, elapsed time, and activity log.
 * Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5
 */
export default function ProgressSection({ analysis }: ProgressSectionProps) {
  const [elapsed, setElapsed] = useState(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (analysis.status === "in_progress") {
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
  }, [analysis.status]);

  const minutes = Math.floor(elapsed / 60);
  const seconds = elapsed % 60;
  const timeStr = `${minutes}:${seconds.toString().padStart(2, "0")}`;

  return (
    <Container
      header={
        <Header
          variant="h2"
          description={`Elapsed time: ${timeStr}`}
        >
          Analysis Progress
        </Header>
      }
    >
      <SpaceBetween size="l">
        <ProgressBar
          value={analysis.progress}
          additionalInfo={analysis.progressMessage}
          status={analysis.status === "failed" ? "error" : "in-progress"}
        />

        <Table
          columnDefinitions={[
            {
              id: "timestamp",
              header: "Timestamp",
              cell: (item) => item.timestamp,
              width: 120,
            },
            {
              id: "title",
              header: "Event",
              cell: (item) => item.title,
              width: 200,
            },
            {
              id: "details",
              header: "Details",
              cell: (item) => item.details,
            },
          ]}
          items={analysis.activityLog}
          empty={
            <Box textAlign="center" color="inherit">
              No activity yet
            </Box>
          }
          variant="embedded"
        />
      </SpaceBetween>
    </Container>
  );
}
