/**
 * useAlphaTab — manages the alphaTab rendering lifecycle.
 *
 * alphaTab is dynamically imported (lazy) so it does not bloat the main
 * bundle. The hook loads a score from an ArrayBuffer into a DOM element
 * and tears down the API instance on unmount or when new data arrives.
 */

import { useEffect, useRef, useState, useCallback } from "react";

// alphaTab's types are only available after dynamic import, so we use
// a loose structural type here to avoid pulling the package into the
// main bundle at build time.
interface AlphaTabApi {
  render(): void;
  destroy(): void;
  tex(content: string): void;
  load(data: ArrayBuffer | Uint8Array, trackIndexes?: number[]): void;
}

interface AlphaTabModule {
  AlphaTabApi: new (
    element: HTMLElement,
    settings: Record<string, unknown>,
  ) => AlphaTabApi;
  Settings: {
    fromJson(json: string): unknown;
  };
}

interface UseAlphaTabResult {
  /** Attach this ref to the container element where alphaTab should render. */
  containerRef: React.RefObject<HTMLDivElement>;
  /** Whether the alphaTab module is currently loading. */
  isLoading: boolean;
  /** Error message if loading or rendering failed. */
  error: string | null;
}

/**
 * Render a score (ArrayBuffer of .gp5 / .gp4 / .gpx / .capx) into a container.
 *
 * @param scoreData The score file as an ArrayBuffer, or null to clear.
 */
export function useAlphaTab(scoreData: ArrayBuffer | null): UseAlphaTabResult {
  const containerRef = useRef<HTMLDivElement>(null);
  const apiRef = useRef<AlphaTabApi | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const destroyApi = useCallback(() => {
    if (apiRef.current) {
      try {
        apiRef.current.destroy();
      } catch {
        // ignore — component may already be gone
      }
      apiRef.current = null;
    }
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function renderScore(): Promise<void> {
      const container = containerRef.current;
      if (!container || !scoreData) {
        destroyApi();
        return;
      }

      setIsLoading(true);
      setError(null);

      try {
        // Lazy-load alphaTab to keep the main bundle small.
        const mod = (await import("@coderline/alphatab")) as unknown as AlphaTabModule;

        if (cancelled) return;

        // Tear down any previous instance before creating a new one.
        destroyApi();

        const settings = {
          core: {
            fontDirectory: "/font/",
            engine: "svg",
            // alphaTab defaults to rendering in a Web Worker, but worker-script
            // auto-detection is unreliable under Vite (both dev and build) and
            // the render silently produces nothing.  Render synchronously on
            // the main thread instead — the scores here are small.
            useWorkers: false,
          },
          player: {
            enable: false,
          },
        };

        const api = new mod.AlphaTabApi(container, settings);
        apiRef.current = api;
        // `load()` parses the score and triggers rendering automatically (its
        // callback calls renderScore internally), so no explicit render() call
        // is needed.  Omit trackIndexes to render the first track, which is
        // what FretPilot produces (a single guitar track).
        const ok = api.load(scoreData);
        // eslint-disable-next-line no-console
        console.log(
          `[alphaTab] load() -> ${ok}, container children: ${container.children.length}`,
        );
      } catch (err) {
        if (!cancelled) {
          // eslint-disable-next-line no-console
          console.error("[alphaTab] render failed:", err);
          setError(
            err instanceof Error
              ? err.message
              : "Failed to render score with alphaTab.",
          );
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    void renderScore();

    return () => {
      cancelled = true;
    };
  }, [scoreData, destroyApi]);

  // Clean up on unmount.
  useEffect(() => {
    return () => {
      destroyApi();
    };
  }, [destroyApi]);

  return { containerRef, isLoading, error };
}
