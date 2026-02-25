import { useQuery } from "@tanstack/react-query";
import { listProjectTasks } from "../api/tasks";
import { useBoardStore } from "../store/boardStore";
import type { TasksByStatus } from "../types";

export function useBoard(projectId: string) {
  const eventVersion = useBoardStore((s) => s.eventVersion);

  return useQuery<TasksByStatus>({
    queryKey: ["board", projectId, eventVersion],
    queryFn: () => listProjectTasks(projectId),
  });
}
