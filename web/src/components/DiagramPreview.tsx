import { useEffect, useRef, useState } from "react";

const EMBED_ORIGIN = "https://embed.diagrams.net";
const EMBED_URL = `${EMBED_ORIGIN}/?embed=1&ui=atlas&spin=1&proto=json`;

interface DiagramPreviewProps {
  xml: string;
}

export function DiagramPreview({ xml }: DiagramPreviewProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setReady(false);

    const loadXml = () => {
      iframeRef.current?.contentWindow?.postMessage(
        JSON.stringify({ action: "load", xml }),
        EMBED_ORIGIN,
      );
    };

    const handleMessage = (event: MessageEvent) => {
      if (event.origin !== EMBED_ORIGIN || event.source !== iframeRef.current?.contentWindow) {
        return;
      }

      let message: { event?: string };
      try {
        message = typeof event.data === "string" ? JSON.parse(event.data) : event.data;
      } catch {
        return;
      }

      if (message.event === "init") {
        loadXml();
      } else if (message.event === "load") {
        setReady(true);
      }
    };

    window.addEventListener("message", handleMessage);
    if (iframeRef.current?.contentDocument?.readyState === "complete") {
      loadXml();
    }

    return () => window.removeEventListener("message", handleMessage);
  }, [xml]);

  return (
    <div className="relative h-[420px] min-w-0 w-full overflow-hidden rounded-lg border border-border bg-white">
      {!ready && (
        <div className="pointer-events-none absolute inset-0 z-10 grid place-items-center bg-surface/90 text-xs text-text-tertiary">
          Loading draw.io preview…
        </div>
      )}
      <iframe
        ref={iframeRef}
        title="Generated draw.io diagram preview"
        src={EMBED_URL}
        onLoad={() => {
          iframeRef.current?.contentWindow?.postMessage(
            JSON.stringify({ action: "load", xml }),
            EMBED_ORIGIN,
          );
        }}
        className="block h-full w-full max-w-full border-0"
        loading="lazy"
      />
    </div>
  );
}
