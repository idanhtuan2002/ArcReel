/**
 * Port side of the donor parity harness for group, storyboard and sibling behavior.
 * Ids created by the reducers are `n1`, `n2`, ... in creation order; the donor
 * side renames its random ids the same way. Localized names are not compared.
 */

import {
  createGraphState,
  loadGraph,
  redo,
  selectNode,
  undo,
} from "../domain/graph";
import {
  type GroupDeps,
  addStoryboardMembers,
  arrangeGroupChildren,
  convertStoryboardGroupToPlain,
  duplicateNodeAsSibling,
  duplicateNodesAsSiblings,
  fitGroupToChildren,
  groupNodes,
  mergeStoryboardGroup,
  reorderStoryboardMember,
  setStoryboardGroupConfig,
  ungroupNode,
} from "../domain/groups";
import type {
  CanvasEdge,
  CanvasGraphState,
  CanvasNode,
  CanvasNodeType,
} from "../domain/types";

export interface GroupFixtureNode {
  id: string;
  type: CanvasNodeType;
  x?: number;
  y?: number;
  w?: number;
  h?: number;
  parentId?: string;
}

export type GroupOp = { op: string } & Record<string, unknown>;

export interface GroupCase {
  id: string;
  behaviors: string[];
  ops: GroupOp[];
}

const STORYBOARD_KEYS = [
  "storyboardGroup",
  "storyboardAspect",
  "storyboardCols",
  "storyboardShowIndex",
  "storyboardBaseWidth",
  "storyboardBaseHeight",
] as const;

export function toFixtureNode(item: GroupFixtureNode): CanvasNode {
  return {
    id: item.id,
    type: item.type,
    position: { x: item.x ?? 0, y: item.y ?? 0 },
    data: {},
    ...(item.w !== undefined ? { width: item.w } : {}),
    ...(item.h !== undefined ? { height: item.h } : {}),
    ...(item.parentId ? { parentId: item.parentId } : {}),
  };
}

export function observeGroups(op: string, state: CanvasGraphState) {
  return {
    op,
    nodes: state.nodes.map((node) => ({
      id: node.id,
      type: node.type,
      parentId: node.parentId ?? null,
      x: node.position.x,
      y: node.position.y,
      width: node.width ?? null,
      height: node.height ?? null,
      styleWidth: node.style?.width ?? null,
      styleHeight: node.style?.height ?? null,
      hidden: node.hidden ?? false,
      selected: node.selected ?? false,
      dragHandle: node.dragHandle ?? null,
      storyboard: Object.fromEntries(
        STORYBOARD_KEYS.filter((key) => key in node.data).map((key) => [
          key,
          node.data[key],
        ]),
      ),
    })),
    edges: state.edges.map((edge: CanvasEdge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      hidden: edge.hidden ?? false,
      origSource: (edge.data?.__sbOrigSource as string | undefined) ?? null,
      origTarget: (edge.data?.__sbOrigTarget as string | undefined) ?? null,
    })),
    past: state.history.past.length,
    future: state.history.future.length,
    selected: state.selectedNodeId,
    edits: state.userEditsSinceHydrate,
  };
}

function deps(): GroupDeps {
  let counter = 0;
  return {
    newId: () => {
      counter += 1;
      return `n${counter}`;
    },
    naming: {
      group: (index) => `Group ${index}`,
      storyboard: (index) => `Storyboard ${index}`,
      copy: (name) => `${name} copy`,
      frame: () => "Frame",
    },
  };
}

export function runGroupCase(fixture: GroupCase) {
  let state = createGraphState();
  const ids = deps();
  const observations: ReturnType<typeof observeGroups>[] = [];
  for (const op of fixture.ops) {
    const arg = op as unknown as Record<string, never>;
    switch (op.op) {
      case "load":
        state = loadGraph(
          state,
          (arg.nodes as GroupFixtureNode[]).map(toFixtureNode),
          (arg.edges as { id: string; source: string; target: string }[]).map(
            (edge) => ({ ...edge }),
          ),
        );
        break;
      case "reload":
        state = loadGraph(state, state.nodes, state.edges);
        break;
      case "select":
        state = selectNode(state, arg.id);
        break;
      case "undo":
        state = undo(state).state;
        break;
      case "redo":
        state = redo(state).state;
        break;
      case "group":
        state = groupNodes(state, arg.ids, ids, {
          extraPadding: arg.extraPadding,
        }).state;
        break;
      case "ungroup":
        state = ungroupNode(state, arg.id).state;
        break;
      case "fit":
        state = fitGroupToChildren(state, arg.id);
        break;
      case "arrange":
        state = arrangeGroupChildren(state, arg.id, arg.mode);
        break;
      case "merge":
        state = mergeStoryboardGroup(state, arg.ids, ids).state;
        break;
      case "sbConfig":
        state = setStoryboardGroupConfig(state, arg.id, arg.config);
        break;
      case "sbReorder":
        state = reorderStoryboardMember(state, arg.id, arg.from, arg.to);
        break;
      case "sbAdd":
        state = addStoryboardMembers(
          state,
          arg.id,
          (arg.frames as string[]).map((assetRef) => ({ assetRef })),
          ids,
        );
        break;
      case "sbConvert":
        state = convertStoryboardGroupToPlain(state, arg.id);
        break;
      case "dupSibling":
        state = duplicateNodeAsSibling(state, arg.id, arg.index, ids).state;
        break;
      case "dupSiblings":
        state = duplicateNodesAsSiblings(state, arg.ids, ids).state;
        break;
      default:
        throw new Error(`unknown op ${op.op}`);
    }
    observations.push(observeGroups(op.op, state));
  }
  return observations;
}
