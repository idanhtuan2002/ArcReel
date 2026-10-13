import { afterEach, describe, expect, it, vi } from "vitest";

import { deriveSpatialFrame, executeSpatial, frameCommandId, getSpatialRevision, listSpatialSources } from "./spatialClient";

const SOURCE = { artifact_key: "artifact-key-v1:abc", shot_id: "SH01", master_version: 2 };

function respond(body: unknown) {
  return vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(() =>
      Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } })),
    );
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("spatial client", () => {
  it("scopes every call to the project and sends exact bodies", async () => {
    const fetch = respond({});
    const controller = new AbortController();

    await listSpatialSources("my project", 3, { signal: controller.signal });
    await deriveSpatialFrame("my project", SOURCE, 4);
    await executeSpatial("my project", {
      commandId: "c1",
      candidateId: "spatial-1",
      episode: 3,
      sceneName: "Lobby",
      master: { receipt_id: "m", receipt_digest: "dm" },
      reverse: { receipt_id: "r", receipt_digest: "dr" },
    });
    await getSpatialRevision("my project", { candidate_id: "spatial-1", current_revision: 2, head_version: 2 });

    expect(fetch.mock.calls.map(([url]) => url)).toEqual([
      "/api/v1/projects/my%20project/m8/spatial/sources?episode=3",
      "/api/v1/projects/my%20project/m8/spatial/frames",
      "/api/v1/projects/my%20project/m8/spatial/executions",
      "/api/v1/projects/my%20project/m8/exploration/candidates/spatial-1/revisions/2",
    ]);
    expect(fetch.mock.calls[0][1]?.signal).toBe(controller.signal);
    expect(JSON.parse(String(fetch.mock.calls[1][1]?.body))).toEqual({
      parent_artifact_key: SOURCE.artifact_key,
      expected_master_version: 2,
      decoded_frame_index: 4,
      command_id: frameCommandId(SOURCE, 4),
    });
    expect(JSON.parse(String(fetch.mock.calls[2][1]?.body))).toEqual({
      command_id: "c1",
      candidate_id: "spatial-1",
      expected_head_version: null,
      episode: 3,
      scene_name: "Lobby",
      master: { receipt_id: "m", receipt_digest: "dm" },
      reverse: { receipt_id: "r", receipt_digest: "dr" },
    });
  });

  it("derives the frame command from the exact source, version and frame", () => {
    expect(frameCommandId(SOURCE, 4)).toBe("frame:artifact-key-v1:abc:2:4");
    expect(frameCommandId({ ...SOURCE, master_version: 3 }, 4)).not.toBe(frameCommandId(SOURCE, 4));
  });
});
