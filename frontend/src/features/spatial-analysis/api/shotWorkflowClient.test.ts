import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createBinding,
  decidePair,
  fetchReviewFrame,
  promote,
  sha256Digest,
  type ReviewSnapshot,
  type TargetVersionRef,
} from "./shotWorkflowClient";

const TARGET: TargetVersionRef = { target_type: "SHOT", target_id: "scene-1-TAKE-1", registry_version: 1, version_digest: "sha256:t" };
const SCENE: TargetVersionRef = { target_type: "SCENE", target_id: "scene-1", registry_version: 1, version_digest: "sha256:s" };

function respond(body: unknown, headers: Record<string, string> = { "Content-Type": "application/json" }) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(() => Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers })));
}

function sent(fetch: ReturnType<typeof respond>, index = 0): unknown {
  return JSON.parse(String(fetch.mock.calls[index][1]?.body));
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("shot workflow client", () => {
  it("binds the two receipts sorted by receipt ID with a command derived from them", async () => {
    const fetch = respond({ binding_id: "b" });

    await createBinding("p", TARGET, [
      { receipt_id: "z", receipt_digest: "dz" },
      { receipt_id: "a", receipt_digest: "da" },
    ]);

    expect(fetch.mock.calls[0][0]).toBe("/api/v1/projects/p/m8/spatial/bindings");
    expect(sent(fetch)).toEqual({
      command_id: "binding:scene-1-TAKE-1:1:a+z",
      expected_target_ref: TARGET,
      ordered_frame_receipts: [
        { receipt_id: "a", receipt_digest: "da" },
        { receipt_id: "z", receipt_digest: "dz" },
      ],
    });
  });

  it("repeats exactly what the review showed and never sends scope or evidence", async () => {
    const fetch = respond({});
    const snapshot: ReviewSnapshot = {
      session_id: "s1",
      scene_ref: SCENE,
      target_ref: TARGET,
      binding_id: "m8b:x",
      binding_version: 1,
      envelope_digest: "sha256:e",
      core_digest: "sha256:c",
      frames: [
        { role: "MASTER", receipt_id: "a", receipt_digest: "da", png_digest: "sha256:pa" },
        { role: "REVERSE", receipt_id: "z", receipt_digest: "dz", png_digest: "sha256:pz" },
      ],
      expires_at: "2026-10-14T00:10:00Z",
    };
    const observations = { view_coverage: "v", camera_center: "c", yaw_relation: "y", rejection_reason: null };

    await decidePair("p", snapshot, "APPROVE", observations);

    const body = sent(fetch) as Record<string, unknown>;
    expect(body).toEqual({
      command_id: "pair:s1:APPROVE",
      review_session_id: "s1",
      expected_scene_ref: SCENE,
      expected_target_ref: TARGET,
      binding_id: "m8b:x",
      expected_binding_version: 1,
      expected_envelope_digest: "sha256:e",
      expected_core_digest: "sha256:c",
      views: [
        { role: "MASTER", receipt_id: "a", receipt_digest: "da" },
        { role: "REVERSE", receipt_id: "z", receipt_digest: "dz" },
      ],
      decision: "APPROVE",
      observations,
    });
    expect(Object.keys(body)).not.toContain("principal");
    expect(Object.keys(body)).not.toContain("review_evidence_digest");
  });

  it("promotes the previewed digest without naming an actor", async () => {
    const fetch = respond({});

    await promote("p", { preview: { base_preview: { preview_id: "pv", expires_at: "x" } }, preview_digest: "sha256:pd" }, 3);

    expect(sent(fetch)).toEqual({
      command_id: "promote:pv",
      preview_id: "pv",
      preview_digest: "sha256:pd",
      expected_candidate_head_version: 3,
    });
  });

  it("returns review frame bytes with the delivery attempt and digest headers", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(new Uint8Array([1, 2, 3]), {
        status: 200,
        headers: { "X-Review-Attempt-Id": "att-1", "X-Review-Png-Digest": "sha256:pd" },
      }),
    );

    const frame = await fetchReviewFrame("p", "s1", "REVERSE");

    expect(new Uint8Array(frame.bytes)).toEqual(new Uint8Array([1, 2, 3]));
    expect(frame.pngDigest).toBe("sha256:pd");
    expect(frame.attemptId).toBe("att-1");
  });

  it("hashes bytes as sha256 with the digest prefix", async () => {
    expect(await sha256Digest(new TextEncoder().encode("abc").buffer)).toBe(
      "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    );
  });
});
