/**
 * New Canvas nodes: text nodes created from the toolbar, and reference nodes
 * imported from the episode's generated shots. Media nodes keep only a project
 * path (`assetRef`); the bytes stay where the episode keeps them.
 */

import type { EpisodeScript } from "@/types";
import { getScriptItems, type EditorContentMode } from "@/utils/script-shape";

import { mergeStoryboardGroup, type GroupDeps } from "../domain/groups";
import { commitEdit } from "../domain/graph";
import type { CanvasGraphState, CanvasNode, XY } from "../domain/types";

export type TextNodeType = "beat" | "note";

export function createTextNode(id: string, type: TextNodeType, position: XY): CanvasNode {
  return { id, type, position, data: { label: "", text: "" } };
}

export interface EpisodeShot {
  itemId: string;
  image: string | null;
  clip: string | null;
  thumbnail: string | null;
}

/** The generated storyboard images and clips of an episode, in script order. */
export function episodeShots(script: EpisodeScript | null | undefined, mode: EditorContentMode): EpisodeShot[] {
  return getScriptItems(script, mode).flatMap((item) => {
    const record = item as {
      segment_id?: string;
      scene_id?: string;
      shot_id?: string;
      generated_assets?: { storyboard_image?: string | null; video_clip?: string | null; video_thumbnail?: string | null };
    };
    const assets = record.generated_assets;
    const itemId = record.segment_id ?? record.scene_id ?? record.shot_id ?? "";
    if (!itemId || (!assets?.storyboard_image && !assets?.video_clip)) return [];
    return [
      {
        itemId,
        image: assets.storyboard_image ?? null,
        clip: assets.video_clip ?? null,
        thumbnail: assets.video_thumbnail ?? assets.storyboard_image ?? null,
      },
    ];
  });
}

const FRAME_GAP = 40;
const FRAME_WIDTH = 320;
const CLIP_ROW_OFFSET = 520;

/**
 * Add the shots as frame and clip reference nodes at `origin`, and put the
 * frames in one storyboard in script order. One undoable edit.
 */
export function importEpisodeShots(
  state: CanvasGraphState,
  shots: readonly EpisodeShot[],
  origin: XY,
  deps: GroupDeps,
): CanvasGraphState {
  if (shots.length === 0) return state;
  const frames: CanvasNode[] = [];
  const clips: CanvasNode[] = [];
  shots.forEach((shot, index) => {
    const x = origin.x + index * (FRAME_WIDTH + FRAME_GAP);
    if (shot.image) {
      frames.push({
        id: deps.newId(),
        type: "frame",
        position: { x, y: origin.y },
        data: { label: shot.itemId, assetRef: shot.image, sourceItemId: shot.itemId },
      });
    }
    if (shot.clip) {
      clips.push({
        id: deps.newId(),
        type: "clip",
        position: { x, y: origin.y + CLIP_ROW_OFFSET },
        data: { label: shot.itemId, assetRef: shot.clip, thumbnailRef: shot.thumbnail, sourceItemId: shot.itemId },
      });
    }
  });
  const added = commitEdit(state, [...state.nodes, ...frames, ...clips], state.edges);
  if (frames.length < 2) return added;
  const merged = mergeStoryboardGroup(
    added,
    frames.map((frame) => frame.id),
    deps,
  );
  // The storyboard is part of the same edit: keep the single history step of the import.
  return merged.groupId ? { ...merged.state, history: added.history, userEditsSinceHydrate: added.userEditsSinceHydrate } : added;
}
