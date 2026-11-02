# FLUX.2 klein 4B reference-image endpoint (i2i)

The host's FLUX.2 klein endpoint (`../endpoint-definition.json`) is text-to-image only, so storyboards that reference
asset sheets fail with `image_capability_missing_i2i`. This definition is the same graph with three reference slots:
`LoadImage → ImageScaleToTotalPixels (1 MP) → VAEEncode → ReferenceLatent`, chained on the positive conditioning before
`CFGGuider`. Each slot's binding names its `ReferenceLatent.latent` consumer, so fewer references drop the unused chains.

- Validated with `validate_comfyui_definition`: no errors, no warnings; `takes_reference_images` is true.
- Real render on the RTX 2070 (2026-11-02): one asset sheet as reference, 576×1024, 4 steps, 21.1 s;
  `reference-render-proof.jpg` (left: reference sheet, right: output) keeps the character's face, cap and clothes.
- Host setup: add this endpoint as `ce-3` on the ComfyUI provider, a model `flux2-klein-4b-ref-gguf` on it, and set the
  project's `image_provider_i2i` to `custom-3/flux2-klein-4b-ref-gguf` (t2i stays on `flux2-klein-4b-gguf`).
