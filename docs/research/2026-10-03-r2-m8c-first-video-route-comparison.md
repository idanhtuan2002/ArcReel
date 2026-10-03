# M8-C first video-route fixture comparison

Status: **provisional fixture choice, not a production provider decision or M8-C acceptance**. Source inspected at design HEAD `ef82f52295a886cc2b6d01df28ad5477435ad874`. No paid call was made.

## Required first-fixture behavior

The fixture needs two ordered, approved front/reverse frame objects, a Shot with spatial constraints in its compiled prompt, an exact M7 submit tuple, and a provider payload that can be constructed once from pinned bytes and submitted unchanged. It must reject any M4 control or reference that the selected backend cannot represent. A provider accepting two images does not by itself prove that it will obey spatial relations; the gate needs a same-fixture prompt/byte comparison and later product-quality evidence.

## Candidates observed

| Candidate | Repository behavior | Limit for M8-C |
| --- | --- | --- |
| Kling `kling-v3-omni` `videos.multi-image2video` | `_build_payload` sends two ordered `image_list` entries; offline probe returned `multi-image2video` and count 2. `require_submit_route` resolved `kling-videos-multi-image2video@host-video-v1`. This route returns before the `sound` field is added (`lib/video_backends/kling.py:358-411`); its declared reference-route audio track is `ALWAYS_OFF`. | Suitable as the **first offline spatial fixture candidate** for a Shot explicitly requiring silence and no unsupported seed/voice control. Prompt-to-image role alignment still needs a deterministic formatter and fixture. Provider capability confirmation and spatial fidelity are not proven here. |
| DashScope `wan2.7-r2v` `video-synthesis` | `_build_payload` sends two ordered `reference_image` media entries; offline probe returned count 2 and route inventory resolved `dashscope-video-synthesis@host-video-v1`. Its declared audio track is `ALWAYS_ON` (`lib/video_backends/dashscope.py:326-360,518-605`). | Official API material supports mixed image/video references and image-number prompt references. The backend truncates references beyond its limit rather than failing (`:589-597`), so an R2 profile must preflight exact count. `ALWAYS_ON` cannot satisfy a silent Shot; `narration` does not mean that the service will speak the project's narration text. |

Alibaba Cloud's [Wan2.7-R2V API reference](https://help.aliyun.com/zh/model-studio/wan-video-to-video-api-reference) shows ordered `media` with `reference_image` items and image-number prompt references; its [model page](https://help.aliyun.com/zh/model-studio/wan2-7-r2v) states a maximum of five mixed references. The local backend cap is also five. The Kling API documentation was not accessible through the browsing tool, so Kling capability claims above are limited to this repository's implementation and offline probe; they are not a current provider guarantee. No price, availability or release-mode decision was made.

## Fixture direction

Use Kling's registered multi-image route as the first **offline** implementation fixture for an explicitly silent, two-view Shot. Derive a real versioned M4 capability descriptor/profile for this exact backend model and M7 route; map selected capability ID separately from backend model ID; capture front/reverse media bytes in fixed order; include provider-payload digest and route in the host request; and test changed source bytes, order, prompt role binding, unsupported control, and active-task snapshot conflict before any provider submit. If the source or prompt contract cannot represent a required semantic, fail admission. Do not extend this fixture into a paid/production route until official capability evidence and the full route-to-submit gate are independently reviewed.
