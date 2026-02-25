import { useEffect, useRef } from "react";
import { useBoardStore } from "../store/boardStore";

const WS_URL = (import.meta.env.VITE_API_URL ?? "http://localhost:8000")
  .replace(/^http/, "ws") + "/ws";

const MAX_BACKOFF = 30000;

export function useWebSocket(): void {
  const setWsConnected = useBoardStore((s) => s.setWsConnected);
  const bumpVersion = useBoardStore((s) => s.bumpVersion);
  const backoffRef = useRef(1000);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let unmounted = false;

    function connect() {
      if (unmounted) return;

      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        setWsConnected(true);
        backoffRef.current = 1000;
      };

      ws.onmessage = () => {
        bumpVersion();
      };

      ws.onclose = () => {
        setWsConnected(false);
        if (!unmounted) {
          const delay = backoffRef.current;
          backoffRef.current = Math.min(delay * 2, MAX_BACKOFF);
          setTimeout(connect, delay);
        }
      };

      ws.onerror = () => {
        ws.close();
      };
    }

    connect();

    return () => {
      unmounted = true;
      wsRef.current?.close();
    };
  }, [setWsConnected, bumpVersion]);
}
