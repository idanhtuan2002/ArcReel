# M8-C exact frame selection candidate

Status: proposed recipe for the first frame-custody slice, not a registered frame, cross-runtime determinism proof or design acceptance. Source checkout: `design/r2-m8c-binding-authority` at `61c92ac194757730e4bda23670c3ee3f3ae572ce`.

## Selection rule

Use a nonnegative **decoded video-frame index** in the selected first video stream as the authoritative selector for the initial M8-C frame path. The selector is counted from zero in decode order, with no seek. Bind that index, the exact parent master identity/content digest, a versioned recipe, the decoder version/build identity and the resulting PNG digest in the derivation identity and receipt. A display timecode may be derived separately, but it is not the selector or an identity shortcut.

The [FFmpeg `select` filter documentation](https://ffmpeg.org/ffmpeg-filters.html#select_002c-aselect) defines `n` as the sequential frame number starting at zero. The [FFmpeg CLI documentation](https://ffmpeg.org/ffmpeg.html) states that input `-ss` first seeks to a nearby seek point and then decodes/discards with accurate seek; output `-ss` decodes until a timestamp. Both introduce timestamp and seeking semantics that the first source path does not need. This favors an explicit decoded ordinal for the initial bounded video clips. This choice is a design inference from the official semantics, not a claim that ordinal extraction is universally faster or immune to decoder-version changes.

Candidate command for a private temporary PNG, with `N` substituted only after integer validation:

```text
ffmpeg -v error -i PARENT.mp4 -map 0:v:0 -an -sn -dn \
  -vf 'select=eq(n\,N),format=rgb24' -fps_mode passthrough \
  -frames:v 1 -f image2 TEMP.png
```

The [FFmpeg image2 documentation](https://ffmpeg.org/ffmpeg-formats.html#image2-1) supports writing a single image with `-frames:v 1`. `-fps_mode passthrough` avoids frame duplication/drop at the output sync step per the [FFmpeg CLI documentation](https://ffmpeg.org/ffmpeg.html). The decoder output still has to be verified and hashed; the command does not make PNG bytes stable across every FFmpeg build or source codec. Never put an untrusted path or filter expression through a shell; pass validated arguments directly to the process. The output is a private temp file; final publication uses the no-overwrite operation required by the [custody seam note](2026-10-03-r2-m8c-frame-custody-seam.md).

## Bounded local probe

On local FFmpeg `8.0.1-3ubuntu2+esm4`, a synthetic three-frame H.264 `testsrc2` clip at 3 fps was decoded with the candidate command for indices 0, 1 and 2. Each command produced one PNG; the three SHA-256 digests differed (`all_frame_digests_distinct= True`, `frame_count= 3`). This proves only local ordinal selection and output feasibility. It does not test variable-frame-rate input, B-frame reordering, malformed media, cross-build output, live Gate C parent locking or receipt registration.

A follow-up probe requested index 3 from that three-frame clip. FFmpeg exited **0** but produced no output file (`out_of_range_exit= 0 output_exists= False`). The service must check for exactly one valid decoded output and its content digest; process success alone cannot admit a frame.

The service must reject a missing selected stream/frame, a negative or over-limit index, unexpected dimensions/pixel format, decoder failure, output beyond configured size/time limits and source bytes that no longer match the pinned parent. It must rehash the parent before decode and recheck the exact current head, full manifest projection, parent bytes and final frame bytes under the receipt commit boundary. The same recipe/build and output digest must be checked on replay. A decoded ordinal may be reused across two videos but does not itself establish a suitable front/reverse pair; the separate human pair admission remains required.
