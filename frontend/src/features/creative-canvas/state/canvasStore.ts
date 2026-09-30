/**
 * The open Canvas: its graph, viewport bookmarks, load phase and any conflict
 * the persistence layer set aside. One Canvas is open at a time.
 *
 * `edit` is the only path for user interaction; it applies a pure domain
 * function, and counts as an edit for autosave when the domain tracked one.
 * While a conflict is shown the Canvas is read-only: `edit` and
 * `editBookmarks` change nothing.
 * `replace` swaps in content the persistence layer loaded and never triggers
 * a save.
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
  /**
   * "kept": the local work is kept aside and the server content is shown. "unkept": no copy
   * could be stored; the local work is still shown and the server content is not loaded.
   */
  conflictMode: "kept" | "unkept";
  /** Bumped by every user edit; the persistence layer autosaves on change. */
  editSeq: number;
  edit: (update: (graph: CanvasGraphState) => CanvasGraphState) => void;
  editBookmarks: (update: (bookmarks: ViewportBookmarks) => ViewportBookmarks) => void;
  replace: (
    patch: Partial<Pick<CanvasStoreState, "graph" | "bookmarks" | "phase" | "loadError" | "conflict" | "conflictMode">>,
  ) => void;
  reset: () => void;
}

function initial(): Pick<
  CanvasStoreState,
  "graph" | "bookmarks" | "phase" | "loadError" | "conflict" | "conflictMode" | "editSeq"
> {
  return {
    graph: createGraphState(),
    bookmarks: createEmptyBookmarks(),
    phase: "idle",
    loadError: null,
    conflict: null,
    conflictMode: "kept",
    editSeq: 0,
  };
}

export const useCanvasStore = create<CanvasStoreState>()((set) => ({
  ...initial(),
  edit: (update) =>
    set((state) => {
      // Kept-aside work waits for the user's choice: the Canvas is read-only until then.
      if (state.conflict) return state;
      const graph = update(state.graph);
      if (graph === state.graph) return state;
      // Selection and in-progress drags change the graph without counting as an edit.
      const edited = graph.userEditsSinceHydrate !== state.graph.userEditsSinceHydrate;
      return { graph, editSeq: edited ? state.editSeq + 1 : state.editSeq };
    }),
  editBookmarks: (update) =>
    set((state) => {
      if (state.conflict) return state;
      const bookmarks = update(state.bookmarks);
      return bookmarks === state.bookmarks ? state : { bookmarks, editSeq: state.editSeq + 1 };
    }),
  replace: (patch) => set(patch),
  reset: () => set(initial()),
}));
