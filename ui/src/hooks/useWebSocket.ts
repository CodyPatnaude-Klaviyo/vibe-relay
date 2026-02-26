import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useBoardStore } from "../store/boardStore";
import type { BoardData, Task, TaskDetail, WebSocketEvent } from "../types";

const WS_URL = (import.meta.env.VITE_API_URL ?? "http://localhost:8000")
  .replace(/^http/, "ws") + "/ws";

const MAX_BACKOFF = 30000;

/** Task-level event types whose payload is a full enriched Task object. */
const TASK_EVENTS = new Set([
  "task_created",
  "task_moved",
  "task_cancelled",
  "task_uncancelled",
  "task_updated",
  "plan_approved",
  "task_ready",
  "milestone_completed",
]);

/**
 * Surgically update the board react-query cache with a single task change.
 * Replaces the task in its correct column (or cancelled list) without
 * triggering a full board refetch.
 */
function updateBoardCache(
  queryClient: ReturnType<typeof useQueryClient>,
  task: Task,
) {
  queryClient.setQueriesData<BoardData>(
    { queryKey: ["board", task.project_id] },
    (old) => {
      if (!old) return old;
      const updated: BoardData = {
        ...old,
        tasks: Object.fromEntries(
          Object.entries(old.tasks).map(([stepId, tasks]) => [
            stepId,
            tasks.filter((t) => t.id !== task.id),
          ]),
        ),
        cancelled: old.cancelled.filter((t) => t.id !== task.id),
      };
      if (task.cancelled) {
        updated.cancelled.push(task);
      } else if (updated.tasks[task.step_id]) {
        updated.tasks[task.step_id].push(task);
      }
      return updated;
    },
  );
  // Also update task detail cache if this task is currently being viewed
  queryClient.setQueryData<TaskDetail>(
    ["task", task.id],
    (old) => {
      if (!old) return old;
      return { ...old, ...task };
    },
  );
}

export function useWebSocket(): void {
  const setWsConnected = useBoardStore((s) => s.setWsConnected);
  const backoffRef = useRef(1000);
  const wsRef = useRef<WebSocket | null>(null);
  const queryClient = useQueryClient();

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

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as WebSocketEvent;

          if (TASK_EVENTS.has(data.type)) {
            const task = data.payload as unknown as Task;
            if (task?.id && task?.project_id && task?.step_id) {
              updateBoardCache(queryClient, task);
              return;
            }
          }

          if (data.type === "comment_added") {
            const payload = data.payload as { task_id?: string };
            if (payload.task_id) {
              queryClient.invalidateQueries({
                queryKey: ["task", payload.task_id],
              });
            }
            return;
          }

          if (data.type === "subtasks_created") {
            const payload = data.payload as { project_id?: string };
            if (payload.project_id) {
              queryClient.invalidateQueries({
                queryKey: ["board", payload.project_id],
              });
            }
            return;
          }

          // Unknown event type — invalidate all board queries
          queryClient.invalidateQueries({ queryKey: ["board"] });
        } catch {
          // Parse error — invalidate as fallback
          queryClient.invalidateQueries({ queryKey: ["board"] });
        }
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
  }, [setWsConnected, queryClient]);
}
