import { useQuery } from "@tanstack/react-query";
import { listProjectTasks } from "../api/tasks";
import type { BoardData } from "../types";

export function useBoard(projectId: string) {
  return useQuery<BoardData>({
    queryKey: ["board", projectId],
    queryFn: () => listProjectTasks(projectId),
  });
}
