import { useEffect, useState, useRef } from "react";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import ProgressBar from "@cloudscape-design/components/progress-bar";

interface DiscoverProgressSectionProps {
  /** True while a discovery crawl is in flight. */
  discovering: boolean;
  /** The index URL being discovered, shown in the header for context. */
  sourceUrl?: string | null;
}

/**
 * Live progress UI for the discovery flow (first discover + Refresh).
 *
 * Mirrors BatchProgressSection: an elapsed-time counter plus a determinate-
 * looking ProgressBar. A bare spinner reads as "maybe hung"; a moving bar reads
 * as "working and advancing". Discovery is a single crawler-agent call in index
 * mode (~10-60 s cold start), so the bar ramps toward 95% over ~60 s and the
 * parent unmounts this the moment the resource list lands. Cache hits return
 * almost instantly, so this is mostly visible on first-discover / Refresh.
 */
export default function DiscoverProgressSection({
  discovering,
  sourceUrl,
}: DiscoverProgressSectionProps) {
  const [elapsed, setElapsed] = useState(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (discovering) {
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
  }, [discovering]);

  const minutes = Math.floor(elapsed / 60);
  const seconds = elapsed % 60;
  const timeStr = `${minutes}:${seconds.toString().padStart(2, "0")}`;

  // Cap at 95% while in flight so it's obvious we're still waiting on the crawl
  // response; the parent swaps in ResourceSelector the moment results arrive.
  const pct = Math.min(95, Math.floor((elapsed / 60) * 95));

  return (
    <Container
      header={
        <Header
          variant="h2"
          description={`Elapsed time: ${timeStr}${sourceUrl ? `  •  ${sourceUrl}` : ""}`}
        >
          Discovering Resources
        </Header>
      }
    >
      <ProgressBar
        value={pct}
        additionalInfo="Crawling the service index page to enumerate its CloudFormation resources. First-time discovery of a large service can take 30-60 s; cached results return instantly."
        status="in-progress"
      />
    </Container>
  );
}
