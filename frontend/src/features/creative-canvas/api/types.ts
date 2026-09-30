/** Wire shapes of the M8 exploration API (`r2/contracts/advanced_creative.py`, ADR-0098). */

export type Sha256Digest = `sha256:${string}`;

/** A JSON object body, as the server's `CanonicalJsonObject`. */
export type JsonObject = { [key: string]: JsonValue };
export type JsonValue = string | number | boolean | null | JsonValue[] | JsonObject;

export interface LineageBinding {
  project_name: string;
  content_basis_digest: Sha256Digest;
  approved_master_id: string | null;
  approved_master_digest: Sha256Digest | null;
  creative_profile_id: string;
  creative_profile_version: string;
  policy_digest: Sha256Digest;
}

export interface ExplorationContext {
  lineage: LineageBinding;
  created_by: string;
}

export interface CanvasNodeWire {
  node_id: string;
  node_type: string;
  body: JsonObject;
}

export interface CanvasEdgeWire {
  edge_id: string;
  source_node_id: string;
  target_node_id: string;
  edge_type: string;
  body: JsonObject;
}

export interface CanvasCandidateWire {
  kind: "CANVAS";
  graph_schema_version: string;
  nodes: CanvasNodeWire[];
  edges: CanvasEdgeWire[];
  groups: JsonObject[];
  storyboard_order: string[];
  viewport_bookmarks: JsonObject[];
}

export interface CanvasRevisionWire {
  candidate_id: string;
  revision: number;
  kind: "CANVAS";
  parent_revision: number | null;
  payload: CanvasCandidateWire;
  payload_digest: Sha256Digest;
  lineage: LineageBinding;
  created_by: string;
  created_at: string;
}

export interface CandidateHead {
  candidate_id: string;
  current_revision: number;
  head_version: number;
}
