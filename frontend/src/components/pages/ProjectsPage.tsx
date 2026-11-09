import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { errMsg, voidCall, voidPromise } from "@/utils/async";
import { useLocation } from "wouter";
import { AlertTriangle, Bot, Library, Loader2, Plus, Search, Settings, Upload } from "lucide-react";
import { useTranslation } from "react-i18next";
import { OperationsStrip } from "@/features/control-room/OperationsStrip";
import { ProjectLibrary } from "@/features/control-room/ProjectLibrary";
import { API } from "@/api";
import { useProjectsStore } from "@/stores/projects-store";
import { useAppStore } from "@/stores/app-store";
import { useConfigStatusStore } from "@/stores/config-status-store";
import { ArchiveDiagnosticsDialog } from "@/components/shared/ArchiveDiagnosticsDialog";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { GlassModal } from "@/components/ui/GlassModal";
import { SecondaryButton } from "@/components/ui/SecondaryButton";
import { WARM_TONE } from "@/utils/severity-tone";
import { getProjectDisplayName } from "@/utils/project-display";
import { CreateProjectModal } from "./CreateProjectModal";
import { ExternalAgentModal } from "./ExternalAgentModal";
import { rememberAssetLibraryReturnTo } from "./AssetLibraryPage";
import { ICON_BTN_FILLED_CLS } from "@/components/ui/darkroom-tokens";
import { ONBOARDING_ANCHORS } from "@/onboarding/anchors";
import { OnboardingDemoCard } from "@/onboarding/OnboardingDemoCard";
import { useOnboardingStore } from "@/stores/onboarding-store";
import { BRAND } from "@/branding";
import {
  type ImportConflictPolicy,
  type ImportFailureDiagnostics,
  type ProjectSummary,
} from "@/types";

// 控制室（ADR-0122）：顶栏、跨项目运营条、服务端分页的项目库表格；导入/删除/新建的对话框沿用原大厅。

const ACCENT_BUTTON_STYLE: CSSProperties = {
  color: "oklch(0.14 0 0)",
  background:
    "linear-gradient(180deg, var(--color-accent-2), var(--color-accent))",
  boxShadow:
    "inset 0 1px 0 oklch(1 0 0 / 0.3), 0 0 0 1px oklch(0.55 0.10 295 / 0.4), 0 4px 14px -6px var(--color-accent)",
};

interface TopBarProps {
  searchValue: string;
  onSearch: (v: string) => void;
  onImport: () => void;
  onCreate: () => void;
  onSettings: () => void;
  onAssets: () => void;
  onOpenExternalAgent: () => void;
  importing: boolean;
  configIncomplete: boolean;
  searchInputRef: React.RefObject<HTMLInputElement | null>;
}

function TopBar({
  searchValue,
  onSearch,
  onImport,
  onCreate,
  onSettings,
  onAssets,
  onOpenExternalAgent,
  importing,
  configIncomplete,
  searchInputRef,
}: TopBarProps) {
  const { t } = useTranslation(["common", "dashboard", "assets"]);
  return (
    <div
      className="sticky top-0 z-30"
      style={{
        background:
          "linear-gradient(180deg, oklch(0.20 0.011 265 / 0.55), oklch(0.15 0.010 265 / 0.45))",
        backdropFilter: "blur(28px) saturate(1.5)",
        WebkitBackdropFilter: "blur(28px) saturate(1.5)",
        borderBottom: "1px solid oklch(1 0 0 / 0.06)",
        boxShadow:
          "inset 0 1px 0 oklch(1 0 0 / 0.05), 0 6px 24px -12px oklch(0 0 0 / 0.45)",
      }}
    >
      <div className="mx-auto flex max-w-[1320px] flex-wrap items-center gap-4 px-4 py-3 sm:px-6">
        <div className="flex items-center gap-2.5">
          <img
            src="/android-chrome-192x192.png"
            alt={BRAND.name}
            className="h-8 w-8 rounded-lg"
          />
          <span
            className="font-sans text-[17px] font-medium tracking-[-0.012em] text-text"
            aria-hidden
          >
            {BRAND.name}
          </span>
        </div>

        <label className="ml-2 flex w-[min(420px,100%)] items-center gap-2 rounded-lg border border-hairline-soft bg-bg/55 px-3 py-1.5 transition-colors focus-within:border-accent/60">
            <Search className="h-3.5 w-3.5 text-text-3" />
            <input
              ref={searchInputRef}
              type="search"
              name="q"
              aria-label={t("dashboard:search_projects")}
              value={searchValue}
              onChange={(e) => onSearch(e.target.value)}
              autoComplete="off"
              spellCheck={false}
              enterKeyHint="search"
              inputMode="search"
              aria-keyshortcuts="Meta+K Control+K"
              placeholder={t("dashboard:lobby_search_placeholder")}
              className="flex-1 bg-transparent text-[12.5px] text-text placeholder:text-text-3 outline-none"
            />
            <kbd
              aria-hidden
              className="rounded border border-hairline-soft px-1.5 py-px font-mono text-[9.5px] text-text-3"
            >
              {t("dashboard:lobby_search_kbd")}
            </kbd>
        </label>

        <div className="ml-auto flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            onClick={onAssets}
            className="inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-[7px] border border-accent/25 bg-accent-dim px-3 py-1.5 text-[12px] text-text-2 transition-colors hover:border-accent/50 hover:bg-accent-soft hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            title={t("assets:library_title")}
          >
            <Library className="h-3.5 w-3.5" />
            {t("assets:library_title")}
          </button>
          <span aria-hidden className="mx-1 h-5 w-px bg-hairline-soft" />
          <button
            type="button"
            onClick={onImport}
            disabled={importing}
            className="inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-[7px] border border-hairline bg-bg-grad-a/50 px-3 py-1.5 text-[12px] text-text-2 transition-colors hover:border-hairline-strong hover:bg-bg-grad-a focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
          >
            {importing ? (
              <Loader2 className="h-3.5 w-3.5 motion-safe:animate-spin" />
            ) : (
              <Upload className="h-3.5 w-3.5" />
            )}
            {importing ? t("dashboard:importing") : t("dashboard:import_zip")}
          </button>
          <button
            type="button"
            onClick={onCreate}
            data-onboarding={ONBOARDING_ANCHORS.lobbyCreateProject}
            className="inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-[7px] px-3.5 py-1.5 text-[12px] font-semibold transition-transform motion-safe:hover:-translate-y-px focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            style={ACCENT_BUTTON_STYLE}
          >
            <Plus className="h-3.5 w-3.5" />
            {t("dashboard:create_project")}
          </button>
          <span aria-hidden className="mx-1 h-5 w-px bg-hairline-soft" />
          <button
            type="button"
            onClick={onOpenExternalAgent}
            className="rounded-md px-2 py-1.5 text-sm text-text-3 transition-colors hover:bg-bg-grad-a hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            title={t("dashboard:external_agent_guide")}
            aria-label={t("dashboard:external_agent_guide")}
          >
            <Bot className="h-4 w-4" aria-hidden />
          </button>
          <button
            type="button"
            onClick={onSettings}
            data-onboarding={ONBOARDING_ANCHORS.lobbySettings}
            className={`relative ${ICON_BTN_FILLED_CLS}`}
            title={t("settings")}
            aria-label={t("settings")}
          >
            <Settings className="h-4 w-4" aria-hidden />
            {configIncomplete ? (
              <span
                aria-label={t("config_incomplete")}
                className="absolute right-0.5 top-0.5 h-2 w-2 rounded-full bg-warm-bright"
              />
            ) : null}
          </button>
        </div>
      </div>
    </div>
  );
}

// -- HeroStrip ----------------------------------------------------------------

export function ProjectsPage() {
  const { t } = useTranslation(["common", "dashboard", "assets"]);
  const [, navigate] = useLocation();
  const { showCreateModal, setShowCreateModal } = useProjectsStore();
  const tourActive = useOnboardingStore((s) => s.active);

  const [importingProject, setImportingProject] = useState(false);
  const [conflictProject, setConflictProject] = useState<string | null>(null);
  const [conflictFile, setConflictFile] = useState<File | null>(null);
  type ImportDiagnosticsState =
    | { source: "success"; diagnostics: ImportFailureDiagnostics; navigateTo: string }
    | { source: "failure"; diagnostics: ImportFailureDiagnostics };
  const [importDiagnostics, setImportDiagnostics] =
    useState<ImportDiagnosticsState | null>(null);
  const [showExternalAgent, setShowExternalAgent] = useState(false);
  const [deletingProject, setDeletingProject] = useState<ProjectSummary | null>(null);
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const importInputRef = useRef<HTMLInputElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const isConfigComplete = useConfigStatusStore((s) => s.isComplete);


  // ADR-0122: the library pages itself on the server; a change here only asks it to read again.
  const [libraryReload, setLibraryReload] = useState(0);
  const fetchProjects = useCallback(() => {
    setLibraryReload((value) => value + 1);
    return Promise.resolve();
  }, []);

  useEffect(() => {
    function handler(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        searchInputRef.current?.focus();
      }
    }
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    await doImport(file);
    e.target.value = "";
  };

  const doImport = async (file: File, policy: ImportConflictPolicy = "prompt") => {
    setImportingProject(true);
    try {
      const result = await API.importProject(file, policy);
      setConflictProject(null);
      setConflictFile(null);
      setImportDiagnostics(null);
      await fetchProjects();

      const autoFixedCount = result.diagnostics.auto_fixed.length;
      const warningCount = result.diagnostics.warnings.length;
      const navigateTo = `/app/projects/${result.project_name}`;
      if (warningCount > 0 || autoFixedCount > 0) {
        useAppStore
          .getState()
          .pushToast(
            autoFixedCount > 0
              ? t("dashboard:import_auto_fixed", {
                  title: getProjectDisplayName(
                    result.project.title,
                    t("dashboard:untitled_project"),
                  ),
                  count: autoFixedCount,
                })
              : t("dashboard:import_success", {
                  title: getProjectDisplayName(
                    result.project.title,
                    t("dashboard:untitled_project"),
                  ),
                }),
            "success",
          );
        setImportDiagnostics({
          source: "success",
          diagnostics: {
            blocking: [],
            auto_fixable: result.diagnostics.auto_fixed,
            warnings: result.diagnostics.warnings,
          },
          navigateTo,
        });
        return;
      }
      navigate(navigateTo);
    } catch (err) {
      const error = err as Error & {
        status?: number;
        conflict_project_name?: string;
        diagnostics?: ImportFailureDiagnostics;
      };

      if (
        error.status === 409 &&
        error.conflict_project_name &&
        policy === "prompt"
      ) {
        setConflictFile(file);
        setConflictProject(error.conflict_project_name);
        return;
      }

      if (error.diagnostics) {
        setImportDiagnostics({ source: "failure", diagnostics: error.diagnostics });
      } else {
        useAppStore
          .getState()
          .pushToast(`${t("dashboard:import_failed")}: ${error.message}`, "warning");
      }
    } finally {
      setImportingProject(false);
    }
  };

  const handleDeleteProject = async () => {
    if (!deletingProject) return;
    const projectDisplayName = deletingProject.title || deletingProject.name;
    setDeleteLoading(true);
    try {
      await API.deleteProject(deletingProject.name);
      await fetchProjects();
      useAppStore.getState().pushToast(t("common:deleted"), "success");
    } catch (err) {
      useAppStore
        .getState()
        .pushToast(
          t("dashboard:delete_project_failed", { title: projectDisplayName, message: errMsg(err) }),
          "warning",
        );
    } finally {
      setDeleteLoading(false);
      setDeletingProject(null);
    }
  };

  return (
    <div
      className="relative min-h-screen text-text"
      style={
        {
          // FilterPills 的 sticky top 读这个变量；TopBar = logo h-8 (32) + py-3 (24) + 1px border
          "--lobby-topbar-h": "57px",
          background:
            "radial-gradient(1100px 540px at 8% -10%, oklch(0.32 0.05 295 / 0.28), transparent 55%), radial-gradient(900px 500px at 100% 110%, oklch(0.26 0.04 260 / 0.25), transparent 55%), linear-gradient(180deg, var(--color-bg-grad-a), var(--color-bg-grad-b))",
        } as CSSProperties
      }
    >
      <TopBar
        searchValue={searchQuery}
        onSearch={setSearchQuery}
        onImport={() => importInputRef.current?.click()}
        onCreate={() => setShowCreateModal(true)}
        onSettings={() => navigate("/app/settings")}
        onAssets={() => {
          rememberAssetLibraryReturnTo(window.location.pathname);
          navigate("/app/assets");
        }}
        onOpenExternalAgent={() => setShowExternalAgent(true)}
        importing={importingProject}
        configIncomplete={!isConfigComplete}
        searchInputRef={searchInputRef}
      />
      <input
        ref={importInputRef}
        type="file"
        accept=".zip,application/zip"
        aria-label={t("dashboard:import_project_file_aria")}
        onChange={voidPromise(handleImport)}
        className="hidden"
      />

      <OperationsStrip />
      {/* 引导运行期间才挂，退出即卸载：首次使用时项目列表通常是空的，演示卡正是那一刻最需要讲的东西。 */}
      {tourActive ? (
        <div className="px-6 pt-4">
          <OnboardingDemoCard />
        </div>
      ) : null}
      <main>
        <ProjectLibrary
          search={searchQuery}
          reload={libraryReload}
          onDelete={setDeletingProject}
          onCreate={() => setShowCreateModal(true)}
        />
      </main>

      {conflictProject && conflictFile && (
        <ConflictDialog
          projectName={conflictProject}
          importing={importingProject}
          onConfirm={(policy) => voidCall(doImport(conflictFile, policy))}
          onCancel={() => {
            setConflictProject(null);
            setConflictFile(null);
          }}
        />
      )}

      {importDiagnostics && (
        <ArchiveDiagnosticsDialog
          title={t(
            importDiagnostics.source === "failure"
              ? "dashboard:import_failure_diagnostics"
              : "dashboard:import_diagnostics",
          )}
          description={t(
            importDiagnostics.source === "failure"
              ? "dashboard:import_failure_with_diagnostics"
              : "dashboard:import_success_with_diagnostics",
          )}
          sections={[
            {
              key: "blocking",
              title: t("dashboard:blocking_issues"),
              severity: "blocking",
              items: importDiagnostics.diagnostics.blocking,
            },
            {
              key: "auto_fixed",
              title: t("dashboard:auto_fixed_issues"),
              severity: "auto_fixed",
              items: importDiagnostics.diagnostics.auto_fixable,
            },
            {
              key: "warnings",
              title: t("dashboard:diagnostics_warnings"),
              severity: "warnings",
              items: importDiagnostics.diagnostics.warnings,
            },
          ]}
          onClose={() => {
            const target =
              importDiagnostics.source === "success" ? importDiagnostics.navigateTo : null;
            setImportDiagnostics(null);
            if (target) navigate(target);
          }}
        />
      )}

      {showExternalAgent && (
        <ExternalAgentModal onClose={() => setShowExternalAgent(false)} />
      )}
      {showCreateModal && <CreateProjectModal />}

      <ConfirmDialog
        open={!!deletingProject}
        tone="danger"
        title={t("dashboard:delete_project")}
        description={
          deletingProject
            ? t("dashboard:confirm_delete_project", {
                title: deletingProject.title || deletingProject.name,
              })
            : null
        }
        confirmLabel={t("dashboard:delete_project")}
        loadingLabel={t("dashboard:deleting_project")}
        cancelLabel={t("common:cancel")}
        loading={deleteLoading}
        onCancel={() => {
          if (!deleteLoading) setDeletingProject(null);
        }}
        onConfirm={handleDeleteProject}
      />
    </div>
  );
}

// -- ConflictDialog -----------------------------------------------------------

function ConflictDialog({
  projectName,
  importing,
  onConfirm,
  onCancel,
}: {
  projectName: string;
  importing: boolean;
  onConfirm: (policy: "overwrite" | "rename") => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation(["common", "dashboard"]);
  return (
    <GlassModal
      open
      onClose={onCancel}
      labelledBy="lobby-conflict-title"
      widthClassName="w-full max-w-lg"
      hairlineTone="warm"
      closeOnBackdrop={!importing}
      closeOnEscape={!importing}
    >
      <div className="px-6 pb-6 pt-5">
        <div className="flex items-start gap-3">
          <span
            aria-hidden
            className="grid h-9 w-9 shrink-0 place-items-center rounded-xl"
            style={{
              background:
                "linear-gradient(135deg, var(--color-warm-tint), var(--color-warm-tint-faint))",
              border: `1px solid ${WARM_TONE.ring}`,
              color: WARM_TONE.color,
              boxShadow: `0 8px 18px -8px ${WARM_TONE.glow}`,
            }}
          >
            <AlertTriangle className="h-4 w-4" />
          </span>
          <div className="min-w-0 flex-1 space-y-1.5">
            <h2
              id="lobby-conflict-title"
              className="display-serif text-[17px] font-semibold tracking-tight"
              style={{ color: "var(--color-text)" }}
            >
              {t("dashboard:duplicate_project_id")}
            </h2>
            <p
              className="text-[12.5px] leading-relaxed"
              style={{ color: "var(--color-text-3)" }}
            >
              {t("dashboard:id_intended_hint")}
              <span className="mx-1 rounded bg-bg/70 px-1.5 py-0.5 font-mono text-text">
                {projectName}
              </span>
              {t("dashboard:already_exists_conflict_hint")}
            </p>
          </div>
        </div>

        <div className="mt-5 grid gap-3">
          <button
            type="button"
            onClick={() => onConfirm("overwrite")}
            disabled={importing}
            aria-label={t("dashboard:overwrite_existing")}
            className="flex w-full items-center justify-between rounded-xl border border-warm-ring bg-warm-tint px-4 py-3 text-left text-sm text-warm-bright transition-colors hover:border-warm-bright/60 hover:bg-warm-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-warm-ring disabled:cursor-not-allowed disabled:opacity-60"
          >
            <span>
              <span className="block font-medium">{t("dashboard:overwrite_existing")}</span>
              <span className="mt-1 block text-xs text-warm-fade">
                {t("dashboard:overwrite_hint")}
              </span>
            </span>
            {importing && <Loader2 className="h-4 w-4 motion-safe:animate-spin" />}
          </button>

          <button
            type="button"
            onClick={() => onConfirm("rename")}
            disabled={importing}
            aria-label={t("dashboard:auto_rename_import")}
            className="flex w-full items-center justify-between rounded-xl border border-accent/25 bg-accent-dim px-4 py-3 text-left text-sm text-text transition-colors hover:border-accent/40 hover:bg-accent-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
          >
            <span>
              <span className="block font-medium">{t("dashboard:auto_rename_import")}</span>
              <span className="mt-1 block text-xs text-text-3">
                {t("dashboard:rename_hint")}
              </span>
            </span>
            {importing && <Loader2 className="h-4 w-4 motion-safe:animate-spin" />}
          </button>
        </div>

        <div className="mt-5 flex justify-end">
          <SecondaryButton size="sm" onClick={onCancel} disabled={importing}>
            {t("cancel")}
          </SecondaryButton>
        </div>
      </div>
    </GlassModal>
  );
}
