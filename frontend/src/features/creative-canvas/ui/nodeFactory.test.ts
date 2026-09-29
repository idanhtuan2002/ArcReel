import { describe, expect, it } from "vitest";

import type { EpisodeScript } from "@/types";

import { isStoryboardGroupNode } from "../domain/geometry";
import { createGraphState } from "../domain/graph";
import { membersInReadingOrder } from "../domain/groups";
import { episodeShots, importEpisodeShots } from "./nodeFactory";

const script = {
  episode: 1,
  title: "E1",
  content_mode: "narration",
  segments: [
    { segment_id: "E1S01", generated_assets: { storyboard_image: "storyboards/1.png", video_clip: "videos/1.mp4", video_thumbnail: "thumbnails/1.jpg" } },
    { segment_id: "E1S02", generated_assets: { storyboard_image: null, video_clip: null } },
    { segment_id: "E1S03", generated_assets: { storyboard_image: "storyboards/3.png", video_clip: null } },
    { segment_id: "E1S04" },
  ],
} as unknown as EpisodeScript;

let ids = 0;
const deps = {
  newId: () => `id-${(ids += 1)}`,
  naming: { group: () => "Group", storyboard: () => "Storyboard", copy: (name: string) => name, frame: () => "Frame" },
};

describe("episode shots", () => {
  it("keeps the generated images and clips in script order", () => {
    expect(episodeShots(script, "narration")).toEqual([
      { itemId: "E1S01", image: "storyboards/1.png", clip: "videos/1.mp4", thumbnail: "thumbnails/1.jpg" },
      { itemId: "E1S03", image: "storyboards/3.png", clip: null, thumbnail: "storyboards/3.png" },
    ]);
    expect(episodeShots(null, "narration")).toEqual([]);
  });

  it("imports frames into one storyboard in script order, plus clip references, as one undoable edit", () => {
    const state = importEpisodeShots(createGraphState(), episodeShots(script, "narration"), { x: 0, y: 0 }, deps);

    const board = state.nodes.find((node) => isStoryboardGroupNode(node));
    expect(board).toBeDefined();
    expect(membersInReadingOrder(state.nodes, board?.id ?? "").map((node) => node.data.assetRef)).toEqual([
      "storyboards/1.png",
      "storyboards/3.png",
    ]);
    expect(state.nodes.filter((node) => node.type === "clip").map((node) => node.data)).toEqual([
      { label: "E1S01", assetRef: "videos/1.mp4", thumbnailRef: "thumbnails/1.jpg", sourceItemId: "E1S01" },
    ]);
    expect(state.history.past).toHaveLength(1);
    expect(state.userEditsSinceHydrate).toBe(1);
  });

  it("changes nothing without shots", () => {
    const empty = createGraphState();

    expect(importEpisodeShots(empty, [], { x: 0, y: 0 }, deps)).toBe(empty);
  });
});
