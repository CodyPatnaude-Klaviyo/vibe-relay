import { create } from "zustand";

interface BoardState {
  selectedTaskId: string | null;
  selectTask: (id: string | null) => void;
  wsConnected: boolean;
  setWsConnected: (connected: boolean) => void;
  eventVersion: number;
  bumpVersion: () => void;
}

export const useBoardStore = create<BoardState>((set) => ({
  selectedTaskId: null,
  selectTask: (id) => set({ selectedTaskId: id }),
  wsConnected: false,
  setWsConnected: (connected) => set({ wsConnected: connected }),
  eventVersion: 0,
  bumpVersion: () => set((s) => ({ eventVersion: s.eventVersion + 1 })),
}));
