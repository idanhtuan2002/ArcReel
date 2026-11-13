import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { ApiRequestError } from "@/api";
import { SEVERITY_TONES } from "@/utils/severity-tone";
import { getAutomationSettings, saveAutomationSettings } from "../api/productionRunClient";
import type { AutomationRole, AutomationSettings, RouteSetting } from "../api/types";

const ROLES: readonly AutomationRole[] = ["writer", "script", "reviewer_a", "reviewer_b", "image", "video", "audio"];
/** Roles that may name fallback models (ADR-0139). */
const FALLBACK_ROLES: readonly AutomationRole[] = ["writer", "script"];
const MAX_FALLBACKS = 32;
const FIELD_CLS = "focus-ring rounded-md px-1.5 py-0.5";
const FIELD_STYLE = { border: "1px solid var(--color-hairline-strong)", background: "transparent" };

interface Draft {
  profile_id: string;
  launch_profile_id: string;
  routes: Record<AutomationRole, RouteSetting | null>;
  fallbacks: RouteSetting[];
  currency: string;
  max_cost_minor_units: number;
  max_model_calls: number;
  max_runtime_hours: number;
  max_target_episodes: number;
}

function draftOf(loaded: AutomationSettings): Draft {
  const { settings } = loaded;
  const routes = Object.fromEntries(
    ROLES.map((role) => [role, settings.routes.find((route) => route.role === role) ?? null]),
  ) as Record<AutomationRole, RouteSetting | null>;
  return {
    profile_id: settings.profile_id ?? "",
    launch_profile_id: settings.launch_profile_id,
    routes,
    fallbacks: settings.fallbacks ?? [],
    currency: settings.currency ?? "USD",
    max_cost_minor_units: settings.max_cost_minor_units ?? 500,
    max_model_calls: settings.max_model_calls ?? 2400,
    max_runtime_hours: Math.round((settings.max_runtime_seconds ?? 64800) / 3600),
    max_target_episodes: settings.max_target_episodes ?? 1,
  };
}

interface Props {
  projectName: string;
  /** Called after a save, so readiness can be checked against the new settings. */
  onSaved?: () => void;
}

/**
 * Edit the project's model per role and run limits. The server pins model identities and refuses a cloud model
 * without a per-call ceiling; a model no qualification covers is then named by readiness, never run.
 */
export function AutomationSettingsEditor({ projectName, onSaved }: Props) {
  const { t } = useTranslation("workflow");
  const [loaded, setLoaded] = useState<AutomationSettings | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(async () => {
    setBusy(true);
    setMessage(null);
    try {
      const settings = await getAutomationSettings(projectName);
      setLoaded(settings);
      setDraft(draftOf(settings));
    } catch {
      setMessage({ ok: false, text: t("auto_settings_load_failed") });
    } finally {
      setBusy(false);
    }
  }, [projectName, t]);

  const option = (role: AutomationRole, route: RouteSetting | null) =>
    loaded?.options[role].find((o) => o.provider_id === route?.provider_id && o.model_id === route?.model_id);

  const save = async () => {
    if (!draft) return;
    const routes = ROLES.map((role) => draft.routes[role]);
    if (routes.some((route) => route === null)) {
      setMessage({ ok: false, text: t("auto_settings_role_missing") });
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      await saveAutomationSettings(projectName, {
        profile_id: draft.profile_id || null,
        launch_profile_id: draft.launch_profile_id,
        routes: routes.filter((route): route is RouteSetting => route !== null),
        fallbacks: draft.fallbacks,
        currency: draft.currency,
        max_cost_minor_units: draft.max_cost_minor_units,
        max_model_calls: draft.max_model_calls,
        max_runtime_seconds: draft.max_runtime_hours * 3600,
        max_target_episodes: draft.max_target_episodes,
      });
      setMessage({ ok: true, text: t("auto_settings_saved") });
      onSaved?.();
    } catch (cause) {
      const code = cause instanceof ApiRequestError && cause.code ? cause.code : null;
      setMessage({
        ok: false,
        text: code ? t(`auto_reason_${code}`, { defaultValue: code }) : t("auto_settings_save_failed"),
      });
    } finally {
      setBusy(false);
    }
  };

  const setRoute = (role: AutomationRole, value: string) => {
    if (!draft || !loaded) return;
    const chosen = loaded.options[role].find((o) => `${o.provider_id}/${o.model_id}` === value);
    setDraft({
      ...draft,
      routes: {
        ...draft.routes,
        [role]: chosen ? { role, provider_id: chosen.provider_id, model_id: chosen.model_id } : null,
      },
    });
  };

  const setCeiling = (role: AutomationRole, value: number) => {
    const route = draft?.routes[role];
    if (!draft || !route) return;
    setDraft({ ...draft, routes: { ...draft.routes, [role]: { ...route, max_cost_per_call: value || null } } });
  };

  const fallbacksOf = (role: AutomationRole) => (draft?.fallbacks ?? []).filter((route) => route.role === role);

  const setFallbacks = (role: AutomationRole, next: RouteSetting[]) => {
    if (!draft) return;
    // Keep each role's fallbacks together, in the order the roles are listed.
    const others = draft.fallbacks.filter((route) => route.role !== role);
    const merged = FALLBACK_ROLES.flatMap((r) => (r === role ? next : others.filter((route) => route.role === r)));
    setDraft({ ...draft, fallbacks: merged });
  };

  const setFallback = (role: AutomationRole, index: number, value: string) => {
    if (!loaded) return;
    const chosen = loaded.options[role].find((o) => `${o.provider_id}/${o.model_id}` === value);
    const list = [...fallbacksOf(role)];
    if (chosen) list[index] = { role, provider_id: chosen.provider_id, model_id: chosen.model_id };
    else list.splice(index, 1);
    setFallbacks(role, list);
  };

  const setFallbackCeiling = (role: AutomationRole, index: number, value: number) => {
    const list = [...fallbacksOf(role)];
    list[index] = { ...list[index], max_cost_per_call: value || null };
    setFallbacks(role, list);
  };

  const moveFallback = (role: AutomationRole, index: number, delta: -1 | 1) => {
    const list = [...fallbacksOf(role)];
    const target = index + delta;
    if (target < 0 || target >= list.length) return;
    [list[index], list[target]] = [list[target], list[index]];
    setFallbacks(role, list);
  };

  /** The fallback becomes the role's model; the model it replaces takes its place in the list. */
  const makeDefault = (role: AutomationRole, index: number) => {
    if (!draft) return;
    const list = [...fallbacksOf(role)];
    const chosen = list[index];
    const previous = draft.routes[role];
    if (previous) list[index] = { ...previous, role };
    else list.splice(index, 1);
    const others = draft.fallbacks.filter((route) => route.role !== role);
    const merged = FALLBACK_ROLES.flatMap((r) => (r === role ? list : others.filter((route) => route.role === r)));
    setDraft({ ...draft, routes: { ...draft.routes, [role]: chosen }, fallbacks: merged });
  };

  const numberField = (key: keyof Draft, label: string, min: number, max: number) => (
    <label className="flex items-center gap-2">
      <span className="w-40" style={{ color: "var(--color-text-2)" }}>
        {label}
      </span>
      <input
        type="number"
        className={`${FIELD_CLS} w-28`}
        style={FIELD_STYLE}
        min={min}
        max={max}
        value={draft ? Number(draft[key]) : 0}
        onChange={(event) => draft && setDraft({ ...draft, [key]: Number(event.target.value) })}
      />
    </label>
  );

  return (
    <details
      className="text-[12px]"
      onToggle={(event) => {
        if ((event.currentTarget).open && loaded === null && !busy) void load();
      }}
    >
      <summary className="cursor-pointer" style={{ color: "var(--color-text-2)" }}>
        {t("auto_settings_title")}
      </summary>
      {draft && loaded && (
        <form
          className="mt-1 space-y-1.5"
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          {loaded.quality_profiles.length === 0 && (
            <p style={{ color: SEVERITY_TONES.warnings.color }}>{t("auto_settings_no_profile")}</p>
          )}
          <label className="flex items-center gap-2">
            <span className="w-40" style={{ color: "var(--color-text-2)" }}>
              {t("auto_settings_quality_profile")}
            </span>
            <select
              className={FIELD_CLS}
              style={FIELD_STYLE}
              value={draft.profile_id}
              onChange={(event) => setDraft({ ...draft, profile_id: event.target.value })}
            >
              <option value="">{t("auto_settings_choose")}</option>
              {loaded.quality_profiles.map((profile) => (
                <option key={profile.profile_id} value={profile.profile_id}>
                  {profile.profile_id} r{profile.revision}
                  {profile.automatic ? "" : ` · ${t("auto_settings_profile_not_automatic")}`}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2">
            <span className="w-40" style={{ color: "var(--color-text-2)" }}>
              {t("auto_settings_launch_profile")}
            </span>
            <select
              className={FIELD_CLS}
              style={FIELD_STYLE}
              value={draft.launch_profile_id}
              onChange={(event) => setDraft({ ...draft, launch_profile_id: event.target.value })}
            >
              {loaded.launch_profiles.map((profile) => (
                <option key={profile} value={profile}>
                  {profile}
                </option>
              ))}
            </select>
          </label>
          {ROLES.map((role) => {
            const route = draft.routes[role];
            const chosen = option(role, route);
            return (
              <div key={role} className="flex flex-wrap items-center gap-2">
                <label className="flex items-center gap-2">
                  <span className="w-40" style={{ color: "var(--color-text-2)" }}>
                    {t(`auto_role_${role}`)}
                  </span>
                  <select
                    className={FIELD_CLS}
                    style={FIELD_STYLE}
                    value={route ? `${route.provider_id}/${route.model_id}` : ""}
                    onChange={(event) => setRoute(role, event.target.value)}
                  >
                    <option value="">{t("auto_settings_choose")}</option>
                    {loaded.options[role].map((o) => (
                      <option key={`${o.provider_id}/${o.model_id}`} value={`${o.provider_id}/${o.model_id}`}>
                        {o.label} · {o.local ? t("auto_setup_local") : t("auto_setup_cloud")}
                      </option>
                    ))}
                  </select>
                </label>
                {chosen && !chosen.local && (
                  <label className="flex items-center gap-1">
                    <span style={{ color: "var(--color-text-3)" }}>{t("auto_settings_ceiling")}</span>
                    <input
                      type="number"
                      className={`${FIELD_CLS} w-20`}
                      style={FIELD_STYLE}
                      min={1}
                      max={1000}
                      aria-label={t("auto_settings_ceiling_for", { role: t(`auto_role_${role}`) })}
                      value={route?.max_cost_per_call ?? ""}
                      onChange={(event) => setCeiling(role, Number(event.target.value))}
                    />
                  </label>
                )}
                {FALLBACK_ROLES.includes(role) && loaded && (
                  <div className="w-full space-y-1 pl-6">
                    {fallbacksOf(role).length > 0 && (
                      <p style={{ color: "var(--color-text-3)" }}>
                        {t("auto_settings_fallbacks")} · {t("auto_settings_fallbacks_hint")}
                      </p>
                    )}
                    {fallbacksOf(role).map((fallback, index) => {
                      const spare = option(role, fallback);
                      const n = index + 1;
                      return (
                        <div key={`${fallback.provider_id}/${fallback.model_id}/${n}`} className="flex flex-wrap items-center gap-2">
                          <span style={{ color: "var(--color-text-3)" }}>{n}.</span>
                          <select
                            className={FIELD_CLS}
                            style={FIELD_STYLE}
                            aria-label={t("auto_settings_fallback_for", { n, role: t(`auto_role_${role}`) })}
                            value={`${fallback.provider_id}/${fallback.model_id}`}
                            onChange={(event) => setFallback(role, index, event.target.value)}
                          >
                            {loaded.options[role].map((o) => (
                              <option key={`${o.provider_id}/${o.model_id}`} value={`${o.provider_id}/${o.model_id}`}>
                                {o.label} · {o.local ? t("auto_setup_local") : t("auto_setup_cloud")}
                              </option>
                            ))}
                          </select>
                          {spare && !spare.local && (
                            <input
                              type="number"
                              className={`${FIELD_CLS} w-20`}
                              style={FIELD_STYLE}
                              min={1}
                              max={1000}
                              aria-label={t("auto_settings_ceiling_for", { role: t("auto_settings_fallback_for", { n, role: t(`auto_role_${role}`) }) })}
                              value={fallback.max_cost_per_call ?? ""}
                              onChange={(event) => setFallbackCeiling(role, index, Number(event.target.value))}
                            />
                          )}
                          <button
                            type="button"
                            className="focus-ring rounded-md px-1.5 disabled:opacity-40"
                            style={FIELD_STYLE}
                            aria-label={t("auto_settings_move_up", { n })}
                            disabled={index === 0}
                            onClick={() => moveFallback(role, index, -1)}
                          >
                            ↑
                          </button>
                          <button
                            type="button"
                            className="focus-ring rounded-md px-1.5 disabled:opacity-40"
                            style={FIELD_STYLE}
                            aria-label={t("auto_settings_move_down", { n })}
                            disabled={index === fallbacksOf(role).length - 1}
                            onClick={() => moveFallback(role, index, 1)}
                          >
                            ↓
                          </button>
                          <button
                            type="button"
                            className="focus-ring rounded-md px-1.5"
                            style={{ ...FIELD_STYLE, color: "var(--color-text-2)" }}
                            aria-label={t("auto_settings_make_default_for", { n })}
                            onClick={() => makeDefault(role, index)}
                          >
                            {t("auto_settings_make_default")}
                          </button>
                          <button
                            type="button"
                            className="focus-ring rounded-md px-1.5"
                            style={FIELD_STYLE}
                            aria-label={t("auto_settings_remove_fallback", { n })}
                            onClick={() => setFallback(role, index, "")}
                          >
                            ×
                          </button>
                        </div>
                      );
                    })}
                    {draft.fallbacks.length < MAX_FALLBACKS && loaded.options[role].length > 1 && (
                      <button
                        type="button"
                        className="focus-ring rounded-md px-1.5 py-0.5"
                        style={{ ...FIELD_STYLE, color: "var(--color-text-2)" }}
                        onClick={() => {
                          const taken = new Set(
                            [route, ...fallbacksOf(role)].map((r) => (r ? `${r.provider_id}/${r.model_id}` : "")),
                          );
                          const free = loaded.options[role].find((o) => !taken.has(`${o.provider_id}/${o.model_id}`));
                          if (free) {
                            setFallbacks(role, [
                              ...fallbacksOf(role),
                              { role, provider_id: free.provider_id, model_id: free.model_id },
                            ]);
                          }
                        }}
                      >
                        + {t("auto_settings_add_fallback")}
                      </button>
                    )}
                  </div>
                )}
              </div>
            );
          })}
          {numberField("max_target_episodes", t("auto_settings_episodes"), 1, 12)}
          {numberField("max_model_calls", t("auto_settings_calls"), 1, 5000)}
          {numberField("max_runtime_hours", t("auto_settings_hours"), 1, 48)}
          {numberField("max_cost_minor_units", t("auto_settings_cost", { currency: draft.currency }), 0, 1_000_000)}
          <p style={{ color: "var(--color-text-3)" }}>{t("auto_settings_hint")}</p>
          <button
            type="submit"
            className="focus-ring rounded-md px-2.5 py-1 text-[12px] disabled:opacity-50"
            style={{
              background: "var(--color-accent-dim)",
              border: "1px solid var(--color-accent-soft)",
              color: "var(--color-accent-2)",
            }}
            disabled={busy}
          >
            {t("auto_settings_save")}
          </button>
        </form>
      )}
      {message && (
        <p role="status" style={{ color: message.ok ? "var(--color-accent-2)" : SEVERITY_TONES.blocking.color }}>
          {message.text}
        </p>
      )}
    </details>
  );
}
