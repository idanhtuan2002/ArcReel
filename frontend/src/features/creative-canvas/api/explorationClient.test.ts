import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiRequestError } from "@/api";

import fixture from "../__fixtures__/canonical-digest.json";
import {
  appendCanvasRevision,
  buildCanvasRevision,
  canvasCandidateId,
  getCandidateHead,
  getCanvasRevision,
  getExplorationContext,
} from "./explorationClient";
import type { CanvasCandidateWire, ExplorationContext } from "./types";

const [revisionCase] = fixture.payloads;
const PAYLOAD = JSON.parse(revisionCase.payload) as CanvasCandidateWire;
const CONTEXT: ExplorationContext = { lineage: JSON.parse(revisionCase.lineage), created_by: "default" };

function respond(body: unknown, status = 200) {
  return vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(() =>
      Promise.resolve(
        new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }),
      ),
    );
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("exploration client", () => {
  it("reads the context, head and one revision under the project and candidate scope", async () => {
    const fetch = respond({});
    const controller = new AbortController();

    await getExplorationContext("my project", 2, { signal: controller.signal });
    await getCandidateHead("my project", canvasCandidateId(2));
    await getCanvasRevision("my project", canvasCandidateId(2), 7);

    expect(fetch.mock.calls.map(([url]) => url)).toEqual([
      "/api/v1/projects/my%20project/m8/exploration/context?episode=2",
      "/api/v1/projects/my%20project/m8/exploration/candidates/canvas-episode-2",
      "/api/v1/projects/my%20project/m8/exploration/candidates/canvas-episode-2/revisions/7",
    ]);
    expect(fetch.mock.calls[0][1]?.signal).toBe(controller.signal);
  });

  it("builds a genesis revision with no parent and the server's digest", async () => {
    const revision = await buildCanvasRevision({
      projectName: "demo",
      candidateId: "canvas-episode-1",
      context: CONTEXT,
      payload: PAYLOAD,
      head: null,
      commandId: "c1",
      now: new Date("2026-09-30T00:00:00Z"),
    });

    expect(revision).toMatchObject({ revision: 1, parent_revision: null, created_by: "default" });
    expect(revision.payload_digest).toBe(revisionCase.digest);
    expect(revision.created_at).toBe("2026-09-30T00:00:00.000Z");
  });

  it("builds the next revision on the head it started from", async () => {
    const revision = await buildCanvasRevision({
      projectName: "demo",
      candidateId: "canvas-episode-1",
      context: CONTEXT,
      payload: PAYLOAD,
      head: { candidate_id: "canvas-episode-1", current_revision: 4, head_version: 4 },
      commandId: "c2",
      now: new Date(0),
    });

    expect(revision).toMatchObject({ revision: 5, parent_revision: 4 });
  });

  it("appends with the expected head version and command id", async () => {
    const fetch = respond({ candidate_id: "canvas-episode-1", current_revision: 5, head_version: 5 });
    const revision = await buildCanvasRevision({
      projectName: "demo",
      candidateId: "canvas-episode-1",
      context: CONTEXT,
      payload: PAYLOAD,
      head: { candidate_id: "canvas-episode-1", current_revision: 4, head_version: 4 },
      commandId: "c2",
      now: new Date(0),
    });

    const head = await appendCanvasRevision("demo", revision, 4, "c2");

    expect(head.current_revision).toBe(5);
    const [url, init] = fetch.mock.calls[0];
    expect(url).toBe("/api/v1/projects/demo/m8/exploration/revisions");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual({ candidate: revision, expected_head_version: 4, command_id: "c2" });
  });

  it("rejects with the HTTP status so the save outcome can be classified", async () => {
    respond({ detail: "The canvas changed elsewhere." }, 409);

    const error: unknown = await getCandidateHead("demo", "canvas-episode-1").catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ApiRequestError);
    expect((error as ApiRequestError).status).toBe(409);
    expect((error as ApiRequestError).message).toBe("The canvas changed elsewhere.");
  });
});
