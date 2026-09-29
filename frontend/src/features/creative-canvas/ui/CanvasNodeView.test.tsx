import { act, fireEvent, render, screen } from "@testing-library/react";
import { ReactFlowProvider, useStoreApi, type NodeProps } from "@xyflow/react";
import { useEffect, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { addNode } from "../domain/graph";
import { setNodeMediaActive } from "../domain/lod";
import { useCanvasStore } from "../state/canvasStore";
import { CanvasNodeView } from "./CanvasNodeView";
import { CanvasProjectContext } from "./canvasContext";

function Zoom({ zoom }: { zoom: number }) {
  const store = useStoreApi();
  useEffect(() => {
    store.setState({ transform: [0, 0, zoom] });
  }, [store, zoom]);
  return null;
}

function renderNode(props: { id: string; type: string; data: Record<string, unknown> }, zoom = 1) {
  const wrap = (children: ReactNode) => (
    <CanvasProjectContext.Provider value="demo">
      <ReactFlowProvider>
        <Zoom zoom={zoom} />
        {children}
      </ReactFlowProvider>
    </CanvasProjectContext.Provider>
  );
  const nodeProps = { ...props, selected: false, dragging: false, zIndex: 0, isConnectable: true } as unknown as NodeProps;
  return render(wrap(<CanvasNodeView {...nodeProps} />));
}

describe("canvas node view", () => {
  beforeEach(() => {
    useCanvasStore.getState().reset();
    useCanvasStore.getState().edit((graph) =>
      addNode(graph, { id: "b1", type: "beat", position: { x: 0, y: 0 }, data: { label: "Hook", text: "" } }),
    );
  });

  afterEach(() => {
    setNodeMediaActive("c1", false);
  });

  it("shows named text fields at working zoom", () => {
    renderNode({ id: "b1", type: "beat", data: { label: "Hook", text: "" } });

    expect(screen.getByText("BEAT")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "标题" })).toHaveValue("Hook");
    expect(screen.getByRole("textbox", { name: "内容" })).toBeInTheDocument();
  });

  it("renders a compact card below the LOD zoom", () => {
    renderNode({ id: "b1", type: "beat", data: { label: "Hook", text: "" } }, 0.2);

    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.getByText("Hook")).toBeInTheDocument();
  });

  it("commits a pending edit when the field unmounts without a blur", () => {
    const view = renderNode({ id: "b1", type: "beat", data: { label: "Hook", text: "" } });
    fireEvent.change(screen.getByRole("textbox", { name: "标题" }), { target: { value: "Cold open" } });

    act(() => view.unmount());

    expect(useCanvasStore.getState().graph.nodes[0].data.label).toBe("Cold open");
  });

  it("keeps a node with playing media in full view below the LOD zoom", () => {
    setNodeMediaActive("c1", true);

    renderNode({ id: "c1", type: "clip", data: { label: "Clip", assetRef: "videos/1.mp4" } }, 0.2);

    expect(screen.getByRole("button", { name: "播放视频: Clip" })).toBeInTheDocument();
  });

  it("commits a text edit once on blur and discards it on Escape", () => {
    renderNode({ id: "b1", type: "beat", data: { label: "Hook", text: "" } });
    const title = screen.getByRole("textbox", { name: "标题" });
    const before = useCanvasStore.getState().editSeq;

    fireEvent.change(title, { target: { value: "Changed" } });
    fireEvent.keyDown(title, { key: "Escape" });
    fireEvent.blur(title);
    expect(useCanvasStore.getState().editSeq).toBe(before);

    fireEvent.change(title, { target: { value: "Changed" } });
    fireEvent.blur(title);
    expect(useCanvasStore.getState().editSeq).toBe(before + 1);
    expect(useCanvasStore.getState().graph.nodes[0].data.label).toBe("Changed");
  });
});
