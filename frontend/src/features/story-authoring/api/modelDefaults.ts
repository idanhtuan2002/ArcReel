import { effectiveModel } from "@/components/shared/LayeredModelFields";
import type { StoryRoute } from "./storyClient";

type TextDefaults = { text_backend_complex?: string | null; default_text_backend?: string | null };
export interface StoryDefaults {
  writer: string;
  source: "project" | "system" | "automatic";
  available: boolean;
}

/** Explicit settings keep the existing SCRIPT tier precedence; automatic choices are story-qualified. */
export function resolveStoryDefaults(routes: StoryRoute[], project: TextDefaults, system: TextDefaults): StoryDefaults {
  const projectModel = effectiveModel(project.text_backend_complex, project.default_text_backend);
  const systemModel = effectiveModel(system.text_backend_complex, system.default_text_backend);
  const configured = effectiveModel(projectModel, systemModel);
  const automatic = routes.find((route) => route.enabled);
  const writer = configured ?? (automatic ? `${automatic.provider_id}/${automatic.model_id}` : "");
  return {
    writer,
    source: projectModel ? "project" : systemModel ? "system" : "automatic",
    available: routes.some((route) => `${route.provider_id}/${route.model_id}` === writer && route.enabled),
  };
}
