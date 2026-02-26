import { useState, useMemo } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { BoardData, Dependency, WorkflowStep } from "../types";
import { createTask } from "../api/tasks";
import { TaskCard } from "./TaskCard";
import { PromptEditor } from "./PromptEditor";
import { STEP_PALETTE, withAlpha } from "../utils/colors";

function getStepColor(step: WorkflowStep): string {
  return step.color ?? STEP_PALETTE[step.position % STEP_PALETTE.length];
}

function NewTaskForm({
  projectId,
  stepId,
  onClose,
}: {
  projectId: string;
  stepId: string;
  onClose: () => void;
}) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: () => createTask(projectId, stepId, title, description),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["board", projectId] });
      onClose();
    },
  });

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim()) return;
    mutation.mutate();
  }

  return (
    <form
      onSubmit={handleSubmit}
      style={{
        background: "var(--glass-bg)",
        border: "1px solid var(--glass-border)",
        borderRadius: "var(--card-radius)",
        padding: "10px 12px",
        marginBottom: "8px",
        display: "flex",
        flexDirection: "column",
        gap: "8px",
        backdropFilter: "blur(8px)",
      }}
    >
      <input
        type="text"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Task title"
        autoFocus
        style={{
          background: "var(--bg)",
          border: "1px solid var(--border)",
          borderRadius: "var(--badge-radius)",
          color: "var(--text)",
          padding: "6px 8px",
          fontSize: "13px",
          fontFamily: "inherit",
          width: "100%",
          boxSizing: "border-box",
          outline: "none",
        }}
        onFocus={(e) => (e.currentTarget.style.borderColor = "var(--agent-active)")}
        onBlur={(e) => (e.currentTarget.style.borderColor = "var(--border)")}
      />
      <textarea
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder="Description (optional)"
        rows={2}
        style={{
          background: "var(--bg)",
          border: "1px solid var(--border)",
          borderRadius: "var(--badge-radius)",
          color: "var(--text)",
          padding: "6px 8px",
          fontSize: "13px",
          fontFamily: "inherit",
          resize: "vertical",
          width: "100%",
          boxSizing: "border-box",
          outline: "none",
        }}
        onFocus={(e) => (e.currentTarget.style.borderColor = "var(--agent-active)")}
        onBlur={(e) => (e.currentTarget.style.borderColor = "var(--border)")}
      />
      <div style={{ display: "flex", gap: "6px", justifyContent: "flex-end" }}>
        <button
          type="button"
          onClick={onClose}
          style={{
            background: "none",
            border: "1px solid var(--border)",
            color: "var(--text-muted)",
            borderRadius: "var(--badge-radius)",
            padding: "4px 12px",
            fontSize: "12px",
            cursor: "pointer",
          }}
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={!title.trim() || mutation.isPending}
          style={{
            background: !title.trim() || mutation.isPending ? "var(--border)" : "#3b82f6",
            color: "#fff",
            border: "none",
            borderRadius: "var(--badge-radius)",
            padding: "4px 12px",
            fontSize: "12px",
            fontWeight: 600,
            cursor: !title.trim() || mutation.isPending ? "not-allowed" : "pointer",
          }}
        >
          {mutation.isPending ? "Adding..." : "Add"}
        </button>
      </div>
    </form>
  );
}

function computeBlockedSet(
  dependencies: Dependency[],
  tasks: Record<string, { id: string; step_name: string }[]>,
  steps: WorkflowStep[]
): Set<string> {
  // Find the terminal step (last position)
  const terminalStep = steps.reduce((max, s) => (s.position > max.position ? s : max), steps[0]);

  // Build a set of task IDs at the terminal step
  const doneTaskIds = new Set<string>();
  for (const taskList of Object.values(tasks)) {
    for (const t of taskList) {
      if (t.step_name === terminalStep?.name) {
        doneTaskIds.add(t.id);
      }
    }
  }

  // For each successor, check if all predecessors are done
  const blocked = new Set<string>();
  const successorToPreds = new Map<string, string[]>();
  for (const dep of dependencies) {
    const existing = successorToPreds.get(dep.successor_id) ?? [];
    existing.push(dep.predecessor_id);
    successorToPreds.set(dep.successor_id, existing);
  }

  for (const [successorId, preds] of successorToPreds) {
    const allDone = preds.every((pid) => doneTaskIds.has(pid));
    if (!allDone) {
      blocked.add(successorId);
    }
  }

  return blocked;
}

export function Board({ data, projectId }: { data: BoardData; projectId: string }) {
  const [addingToStep, setAddingToStep] = useState<string | null>(null);
  const [editingPrompt, setEditingPrompt] = useState<{ stepId: string; stepName: string } | null>(null);

  const blockedSet = useMemo(
    () => computeBlockedSet(data.dependencies ?? [], data.tasks, data.steps),
    [data.dependencies, data.tasks, data.steps]
  );

  const columns: (WorkflowStep & { key: string })[] = data.steps.map((s) => ({
    ...s,
    key: s.id,
  }));

  // Add cancelled column if there are cancelled tasks
  const showCancelled = data.cancelled.length > 0;

  return (
    <div
      style={{
        display: "flex",
        gap: "12px",
        padding: "16px",
        overflowX: "auto",
        height: "calc(100vh - 80px)",
      }}
    >
      {columns.map((col) => {
        const tasks = data.tasks[col.id] ?? [];
        const stepColor = getStepColor(col);
        return (
          <div
            key={col.key}
            style={{
              minWidth: "var(--column-width)",
              width: "var(--column-width)",
              display: "flex",
              flexDirection: "column",
              background: "var(--border-subtle)",
              borderRadius: "12px",
              padding: "0 0 8px",
              overflow: "hidden",
            }}
          >
            {/* Column header */}
            <div
              style={{
                padding: "10px 12px",
                fontWeight: 600,
                fontSize: "12px",
                textTransform: "uppercase",
                letterSpacing: "0.5px",
                color: "var(--text-muted)",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                background: "var(--glass-bg)",
                backdropFilter: "blur(8px)",
                borderBottom: `2px solid ${withAlpha(stepColor, 0.4)}`,
                boxShadow: `0 2px 8px ${withAlpha(stepColor, 0.08)}`,
              }}
            >
              <span style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                {col.name}
                {col.has_agent && (
                  <span
                    title="Agent-powered step"
                    style={{
                      width: "6px",
                      height: "6px",
                      borderRadius: "50%",
                      background: "var(--ws-connected)",
                      display: "inline-block",
                      boxShadow: "0 0 4px var(--ws-connected)",
                    }}
                  />
                )}
              </span>
              <span style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <span
                  style={{
                    background: withAlpha(stepColor, 0.15),
                    color: stepColor,
                    padding: "1px 7px",
                    borderRadius: "10px",
                    fontSize: "11px",
                    fontWeight: 600,
                    minWidth: "20px",
                    textAlign: "center",
                  }}
                >
                  {tasks.length}
                </span>
                {col.has_agent && (
                  <button
                    onClick={() => setEditingPrompt({ stepId: col.id, stepName: col.name })}
                    title={`Edit ${col.name} prompt`}
                    style={{
                      background: "none",
                      border: "1px solid transparent",
                      color: "var(--text-dim)",
                      fontSize: "12px",
                      cursor: "pointer",
                      padding: "0 4px",
                      lineHeight: 1,
                      borderRadius: "var(--badge-radius)",
                      transition: "border-color 0.15s ease, color 0.15s ease",
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.borderColor = "var(--border)";
                      e.currentTarget.style.color = "var(--text)";
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.borderColor = "transparent";
                      e.currentTarget.style.color = "var(--text-dim)";
                    }}
                  >
                    ✎
                  </button>
                )}
                <button
                  onClick={() => setAddingToStep(addingToStep === col.id ? null : col.id)}
                  title={`Add task to ${col.name}`}
                  style={{
                    background: "none",
                    border: "1px solid transparent",
                    color: "var(--text-muted)",
                    fontSize: "16px",
                    cursor: "pointer",
                    padding: "0 4px",
                    lineHeight: 1,
                    borderRadius: "var(--badge-radius)",
                    transition: "border-color 0.15s ease, color 0.15s ease",
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.borderColor = "var(--border)";
                    e.currentTarget.style.color = "var(--text)";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.borderColor = "transparent";
                    e.currentTarget.style.color = "var(--text-muted)";
                  }}
                >
                  +
                </button>
              </span>
            </div>
            <div style={{ flex: 1, overflowY: "auto", padding: "8px 8px 0" }}>
              {addingToStep === col.id && (
                <NewTaskForm
                  projectId={projectId}
                  stepId={col.id}
                  onClose={() => setAddingToStep(null)}
                />
              )}
              {tasks.length === 0 && addingToStep !== col.id ? (
                <div
                  style={{
                    color: "var(--text-dim)",
                    fontSize: "12px",
                    padding: "24px 16px",
                    textAlign: "center",
                    fontStyle: "italic",
                    border: "1px dashed var(--border)",
                    borderRadius: "var(--card-radius)",
                    margin: "4px 0",
                  }}
                >
                  No tasks yet
                </div>
              ) : (
                tasks.map((task) => (
                  <TaskCard
                    key={task.id}
                    task={task}
                    isBlocked={blockedSet.has(task.id)}
                  />
                ))
              )}
            </div>
          </div>
        );
      })}

      {/* Prompt editor modal */}
      {editingPrompt && (
        <PromptEditor
          projectId={projectId}
          stepId={editingPrompt.stepId}
          stepName={editingPrompt.stepName}
          onClose={() => setEditingPrompt(null)}
        />
      )}

      {/* Cancelled column */}
      {showCancelled && (
        <div
          style={{
            minWidth: "var(--column-width)",
            width: "var(--column-width)",
            display: "flex",
            flexDirection: "column",
            background: "var(--border-subtle)",
            borderRadius: "12px",
            padding: "0 0 8px",
            overflow: "hidden",
          }}
        >
          <div
            style={{
              padding: "10px 12px",
              fontWeight: 600,
              fontSize: "12px",
              textTransform: "uppercase",
              letterSpacing: "0.5px",
              color: "var(--status-cancelled)",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              background: "var(--glass-bg)",
              backdropFilter: "blur(8px)",
              borderBottom: "2px solid rgba(239, 68, 68, 0.3)",
            }}
          >
            <span>Cancelled</span>
            <span
              style={{
                background: "rgba(239, 68, 68, 0.15)",
                color: "var(--status-cancelled)",
                padding: "1px 7px",
                borderRadius: "10px",
                fontSize: "11px",
                fontWeight: 600,
              }}
            >
              {data.cancelled.length}
            </span>
          </div>
          <div style={{ flex: 1, overflowY: "auto", padding: "8px 8px 0" }}>
            {data.cancelled.map((task) => (
              <TaskCard key={task.id} task={task} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
