/**
 * The React Flow surface over the Canvas store. React Flow renders; every
 * change goes back through the pure domain reducers.
 *
 * Rendering stays inside the benchmark envelope by: rendering only visible
 * elements, one memoized node component, a boolean LOD selector per node, and
 * turning shadows and transitions off while the view or a node is moving.
 */
import { useCallback, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlow,
  type Connection as FlowConnection,
  type Edge,
  type EdgeChange,
  type Node,
  type NodeChange as FlowNodeChange,
  type NodeTypes,
} from "@xyflow/react";

import { addEdge, deleteEdge } from "../domain/graph";
import type { NodeChange } from "../domain/types";
import { useCanvasStore } from "../state/canvasStore";
import { CanvasNodeView } from "./CanvasNodeView";
import { applyFlowNodeChanges } from "./selection";

const NODE_TYPES: NodeTypes = {
  beat: CanvasNodeView,
  note: CanvasNodeView,
  frame: CanvasNodeView,
  clip: CanvasNodeView,
  audio: CanvasNodeView,
  group: CanvasNodeView,
};

const DELETE_KEYS = ["Backspace", "Delete"];
const MULTI_SELECT_KEYS = ["Shift", "Meta", "Control"];
const PRO_OPTIONS = { hideAttribution: true };

/** The React Flow node changes the domain understands; React Flow's own add/replace are not used. */
export function toDomainChanges(changes: readonly FlowNodeChange[]): NodeChange[] {
  const mapped: NodeChange[] = [];
  for (const change of changes) {
    if (change.type === "position") {
      mapped.push({ type: "position", id: change.id, position: change.position, dragging: change.dragging });
    } else if (change.type === "dimensions") {
      mapped.push({ type: "dimensions", id: change.id, dimensions: change.dimensions, resizing: change.resizing });
    } else if (change.type === "select") {
      mapped.push({ type: "select", id: change.id, selected: change.selected });
    } else if (change.type === "remove") {
      mapped.push({ type: "remove", id: change.id });
    }
  }
  return mapped;
}

interface CanvasBoardProps {
  label: string;
  newId: () => string;
}

export function CanvasBoard({ label, newId }: CanvasBoardProps) {
  const { t } = useTranslation("dashboard");
  const nodes = useCanvasStore((state) => state.graph.nodes) as unknown as Node[];
  const edges = useCanvasStore((state) => state.graph.edges);
  const edit = useCanvasStore((state) => state.edit);
  const [selectedEdges, setSelectedEdges] = useState<ReadonlySet<string>>(() => new Set());
  const shellRef = useRef<HTMLDivElement>(null);

  const flowEdges = useMemo<Edge[]>(
    () => edges.map((edge) => (selectedEdges.has(edge.id) ? { ...edge, selected: true } : edge)),
    [edges, selectedEdges],
  );

  const onNodesChange = useCallback(
    (changes: FlowNodeChange[]) => {
      const mapped = toDomainChanges(changes);
      if (mapped.length > 0) edit((graph) => applyFlowNodeChanges(graph, mapped));
    },
    [edit],
  );

  const onEdgesChange = useCallback(
    (changes: EdgeChange[]) => {
      const removed = changes.flatMap((change) => (change.type === "remove" ? [change.id] : []));
      if (removed.length > 0) edit((graph) => removed.reduce((state, id) => deleteEdge(state, id), graph));
      setSelectedEdges((previous) => {
        const next = new Set(previous);
        for (const change of changes) {
          if (change.type === "select") {
            if (change.selected) next.add(change.id);
            else next.delete(change.id);
          } else if (change.type === "remove") {
            next.delete(change.id);
          }
        }
        return next;
      });
    },
    [edit],
  );

  const onConnect = useCallback(
    (connection: FlowConnection) => edit((graph) => addEdge(graph, connection, newId())),
    [edit, newId],
  );

  const setMoving = useCallback((moving: boolean) => {
    if (!shellRef.current) return;
    if (moving) shellRef.current.dataset.moving = "true";
    else delete shellRef.current.dataset.moving;
  }, []);
  const onMoveStart = useCallback(() => setMoving(true), [setMoving]);
  const onMoveEnd = useCallback(() => setMoving(false), [setMoving]);

  const ariaLabelConfig = useMemo(
    () => ({
      "node.a11yDescription.default": t("creative_canvas_a11y_node"),
      "node.a11yDescription.keyboardDisabled": t("creative_canvas_a11y_node"),
      "node.a11yDescription.ariaLiveMessage": ({ direction, x, y }: { direction: string; x: number; y: number }) =>
        t("creative_canvas_a11y_moved", { direction, x, y }),
      "edge.a11yDescription.default": t("creative_canvas_a11y_edge"),
      "controls.ariaLabel": t("creative_canvas_toolbar_label"),
      "controls.zoomIn.ariaLabel": t("creative_canvas_zoom_in"),
      "controls.zoomOut.ariaLabel": t("creative_canvas_zoom_out"),
      "controls.fitView.ariaLabel": t("creative_canvas_fit"),
      "minimap.ariaLabel": t("creative_canvas_minimap"),
      "handle.ariaLabel": t("creative_canvas_a11y_handle"),
    }),
    [t],
  );

  return (
    <div ref={shellRef} className="canvas-shell h-full w-full">
      <ReactFlow
        aria-label={label}
        nodes={nodes}
        edges={flowEdges}
        nodeTypes={NODE_TYPES}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onMoveStart={onMoveStart}
        onMoveEnd={onMoveEnd}
        onNodeDragStart={onMoveStart}
        onNodeDragStop={onMoveEnd}
        onlyRenderVisibleElements
        nodesFocusable
        edgesFocusable
        deleteKeyCode={DELETE_KEYS}
        multiSelectionKeyCode={MULTI_SELECT_KEYS}
        minZoom={0.05}
        maxZoom={2}
        colorMode="dark"
        ariaLabelConfig={ariaLabelConfig}
        proOptions={PRO_OPTIONS}
        fitView
      >
        <Background variant={BackgroundVariant.Dots} gap={24} size={1} className="canvas-grid" />
        <Controls showInteractive={false} position="bottom-left" />
        <MiniMap pannable zoomable position="bottom-right" className="canvas-minimap" />
      </ReactFlow>
    </div>
  );
}
