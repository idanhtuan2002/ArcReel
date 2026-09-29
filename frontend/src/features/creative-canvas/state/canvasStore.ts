/**
 * The open Canvas: its graph, viewport bookmarks, load phase and any conflict
 * the persistence layer set aside. One Canvas is open at a time.
 *
 * `edit` is the only path for user edits; it applies a pure domain function
 * and counts as an edit for autosave. `replace` swaps in content the
 * persistence layer loaded and never triggers a save.
 */
import { create } from "zustand";

import { createEmptyBookmarks, type ViewportBookmarks } from "../domain/bookmarks";
import { createGraphState } from "../domain/graph";
import type { CanvasGraphState } from "../domain/types";
import type { ConflictSnapshot } from "../recovery/draftRecovery";

export type CanvasPhase = "idle" | "loading" | "ready" | "error";

export interface CanvasStoreState {
  graph: CanvasGraphState;
  bookmarks: ViewportBookmarks;
  phase: CanvasPhase;
  loadError: string | null;
  /** Local content kept aside because the server moved; the user decides what happens to it. */
  conflict: ConflictSnapshot | null;
  /** Bumped by every user edit; the persistence layer autosaves on change. */
  editSeq: number;
  edit: (update: (graph: CanvasGraphState) => CanvasGraphState) => void;
  editBookmarks: (update: (bookmarks: ViewportBookmarks) => ViewportBookmarks) => void;
  replace: (patch: Partial<Pick<CanvasStoreState, "graph" | "bookmarks" | "phase" | "loadError" | "conflict">>) => void;
  reset: () => void;
}

function initial(): Pick<CanvasStoreState, "graph" | "bookmarks" | "phase" | "loadError" | "conflict" | "editSeq"> {
  return {
    graph: createGraphState(),
    bookmarks: createEmptyBookmarks(),
    phase: "idle",
    loadError: null,
    conflict: null,
    editSeq: 0,
  };
}

export const useCanvasStore = create<CanvasStoreState>()((set) => ({
  ...initial(),
  edit: (update) =>
    set((state) => {
      const graph = update(state.graph);
      return graph === state.graph ? state : { graph, editSeq: state.editSeq + 1 };
    }),
  editBookmarks: (update) =>
    set((state) => {
      const bookmarks = update(state.bookmarks);
      return bookmarks === state.bookmarks ? state : { bookmarks, editSeq: state.editSeq + 1 };
    }),
  replace: (patch) => set(patch),
  reset: () => set(initial()),
}));
