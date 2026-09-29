/**
 * Low-detail (LOD) rules of the Canvas. Ported from DramaClaw b299bfd9
 * (`features/canvas/application/canvasLod.ts`): the zoom threshold, the
 * media-active registry and the release delay of the gesture state.
 *
 * Two tiers:
 * - during a gesture (pan, zoom, drag), visual effects are off; they return
 *   `PANNING_CLASS_RELEASE_DELAY_MS` after it ends, which covers the inertia
 *   tail that follows React Flow's move-end event;
 * - below `LOW_DETAIL_ZOOM_THRESHOLD`, nodes render as compact cards: no text
 *   fields, images or video. A node whose media is playing keeps its full view
 *   (the player would lose its position).
 *
 * The donor's layout-measurement signals, shell upgrade pump and hydrate burst
 * are not ported: the ArcReel node view reads no layout while rendering.
 */

/**
 * Below this zoom a node is compact. A standard node (320–400 px wide) is then
 * 110–140 px on screen, where a video frame carries no readable detail; the
 * working range 0.5–1 is unaffected.
 */
export const LOW_DETAIL_ZOOM_THRESHOLD = 0.35;

export function isLowDetailZoom(zoom: number): boolean {
  return Number.isFinite(zoom) && zoom < LOW_DETAIL_ZOOM_THRESHOLD;
}

/**
 * Nodes whose media is playing. Deliberately not reactive: a change takes
 * effect at the next tier crossing or remount, as in the donor.
 */
const mediaActiveNodes = new Set<string>();

export function setNodeMediaActive(nodeId: string, active: boolean): void {
  if (active) mediaActiveNodes.add(nodeId);
  else mediaActiveNodes.delete(nodeId);
}

export function isNodeMediaActive(nodeId: string): boolean {
  return mediaActiveNodes.has(nodeId);
}

/** How long after a gesture ends the effects stay off. */
export const PANNING_CLASS_RELEASE_DELAY_MS = 80;
