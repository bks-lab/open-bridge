import React, { useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";
import "./command-console.css";
const ContentBrowser = React.lazy(() => import("./ContentBrowser"));
import english from "./themes/professional.json";
import german from "./themes/professional-de.json";
type Locale = "en" | "de";
let currentLocale: Locale = "en";
function t(key: keyof typeof english): string {
  return currentLocale === "de" ? german[key] : english[key];
}

type Run = {
  id: string;
  project_id: string;
  project_name: string;
  client: string;
  prompt: string;
  mode: string;
  status: string;
  created_at: string;
  updated_at: string;
  exit_code: number | null;
  error?: string;
};
type Bridge = {
  id: string;
  name: string;
  root: string;
  read_only: boolean;
  content_editable?: boolean;
};
type Bootstrap = {
  csrf: string;
  bridge: Bridge & { language?: string };
  bridges: Bridge[];
  clients: { id: string; available: boolean }[];
  projects: {
    id: string;
    name: string;
    path: string;
    available: boolean;
    archived?: boolean;
  }[];
  tasks: {
    id: string;
    title: string;
    status: string;
    priority: string;
    context?: string;
    path?: string;
  }[];
  runs: Run[];
};
type Detail = {
  run: Run;
  stdout: string;
  stderr: string;
  diff: string;
  changed_files: { path: string; status: string }[];
  review: { branch: string; dirty: boolean; summary: string };
};
const statusLabels = (): Record<string, string> => ({
  queued: t("queued"),
  running: t("running"),
  succeeded: t("completed"),
  failed: t("failed"),
  cancelled: t("cancelled"),
  interrupted: t("interrupted"),
  backlog: t("planned"),
  doing: t("in_progress"),
  review: t("in_review"),
  done: t("done"),
});
const active = (r: Run) => ["queued", "running"].includes(r.status);
const date = (value: string) =>
  new Date(value).toLocaleString(currentLocale === "de" ? "de-DE" : "en-GB", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
function Icon({ name }: { name: string }) {
  const paths: Record<string, React.ReactNode> = {
    grid: (
      <>
        <rect x="3" y="3" width="7" height="7" rx="1" />
        <rect x="14" y="3" width="7" height="7" rx="1" />
        <rect x="3" y="14" width="7" height="7" rx="1" />
        <rect x="14" y="14" width="7" height="7" rx="1" />
      </>
    ),
    play: <path d="m8 5 11 7-11 7Z" />,
    folder: <path d="M3 7V5h7l2 3h9v12H3Z" />,
    arrow: <path d="M5 12h14m-5-5 5 5-5 5" />,
    moon: <path d="M20 15A9 9 0 0 1 9 4a9 9 0 1 0 11 11Z" />,
    search: (
      <>
        <circle cx="10" cy="10" r="6" />
        <path d="m15 15 5 5" />
      </>
    ),
    check: <path d="m5 12 4 4L19 6" />,
  };
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {paths[name] || paths.grid}
    </svg>
  );
}
function BridgeWorkspace() {
  const [bridgeId, setBridgeId] = useState(() => {
    try {
      return sessionStorage.getItem("bridge-selected") || "";
    } catch {
      return "";
    }
  });
  const [bridges, setBridges] = useState<Bridge[]>([]);
  const [selectionNotice, setSelectionNotice] = useState(false);
  const editorState = useRef({ dirty: false, saving: false });
  const reportEditor = useCallback(
    (state: { dirty: boolean; saving: boolean }) => {
      editorState.current = state;
    },
    [],
  );
  const canLeave = useCallback(
    () =>
      !editorState.current.saving &&
      (!editorState.current.dirty ||
        window.confirm(t("discard_unsaved_changes"))),
    [],
  );
  useEffect(() => {
    const guard = (event: BeforeUnloadEvent) => {
      if (editorState.current.dirty || editorState.current.saving) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, []);
  function choose(id: string, invalid = false) {
    if (id === bridgeId || !canLeave()) return;
    try {
      if (id) sessionStorage.setItem("bridge-selected", id);
      else sessionStorage.removeItem("bridge-selected");
    } catch {}
    setSelectionNotice(invalid);
    setBridgeId(id);
  }
  return (
    <App
      key={bridgeId}
      bridgeId={bridgeId}
      bridges={bridges}
      chooseBridge={choose}
      updateBridges={setBridges}
      selectionNotice={selectionNotice}
      canLeave={canLeave}
      reportEditor={reportEditor}
    />
  );
}
function App({
  bridgeId,
  bridges,
  chooseBridge,
  updateBridges,
  selectionNotice,
  canLeave,
  reportEditor,
}: {
  bridgeId: string;
  bridges: Bridge[];
  chooseBridge: (id: string, invalid?: boolean) => void;
  updateBridges: (bridges: Bridge[]) => void;
  selectionNotice: boolean;
  canLeave: () => boolean;
  reportEditor: (state: { dirty: boolean; saving: boolean }) => void;
}) {
  const languagePreference = useRef(
    (() => {
      try {
        return localStorage.getItem("bridge-language");
      } catch {
        return null;
      }
    })(),
  );
  const [locale, setLocale] = useState<Locale>(() => {
    try {
      return localStorage.getItem("bridge-language") === "de" ? "de" : "en";
    } catch {
      return "en";
    }
  });
  currentLocale = locale;
  useEffect(() => {
    document.documentElement.lang = locale;
    try {
      localStorage.setItem("bridge-language", locale);
    } catch {}
  }, [locale]);
  const [scenePaused, setScenePaused] = useState(() => {
    try {
      return localStorage.getItem("bridge-scene-paused") === "true";
    } catch {
      return false;
    }
  });
  function toggleScene() {
    setScenePaused((value) => {
      const next = !value;
      try {
        localStorage.setItem("bridge-scene-paused", String(next));
      } catch {}
      return next;
    });
  }
  const [data, setData] = useState<Bootstrap | null>(null),
    [runs, setRuns] = useState<Run[]>([]),
    [online, setOnline] = useState(false),
    [error, setError] = useState("");
  const [view, setRawView] = useState("overview"),
    [search, setSearch] = useState(""),
    [project, setProject] = useState(""),
    [client, setClient] = useState("codex"),
    [prompt, setPrompt] = useState(""),
    [mode, setMode] = useState("inspect"),
    [trust, setTrust] = useState(false),
    [pending, setPending] = useState(false),
    [cancelling, setCancelling] = useState(false);
  function setView(next: string) {
    if (next === view || view !== "content" || canLeave()) setRawView(next);
  }
  const [contentPath, setContentPath] = useState("");
  const [allProjects, setAllProjects] = useState(false);
  const [projectFilter, setProjectFilter] = useState("available");
  const [preferences, setPreferences] = useState<
    Record<string, { favorite?: boolean; archived?: boolean }>
  >(() => {
    try {
      const value = JSON.parse(
        localStorage.getItem("bridge-project-preferences") || "{}",
      );
      return value && typeof value === "object" && !Array.isArray(value)
        ? value
        : {};
    } catch {
      return {};
    }
  });
  useEffect(() => {
    function synchronize(event: StorageEvent) {
      if (event.key !== "bridge-project-preferences") return;
      try {
        const value = JSON.parse(event.newValue || "{}");
        if (value && typeof value === "object" && !Array.isArray(value))
          setPreferences(value);
      } catch {}
    }
    window.addEventListener("storage", synchronize);
    return () => window.removeEventListener("storage", synchronize);
  }, []);
  function projectKey(id: string) {
    return `${data?.bridge.id}:${id}`;
  }
  function prefer(
    id: string,
    field: "favorite" | "archived",
    current: boolean,
  ) {
    const key = projectKey(id);
    let latest = preferences;
    try {
      const stored = JSON.parse(
        localStorage.getItem("bridge-project-preferences") || "{}",
      );
      if (stored && typeof stored === "object" && !Array.isArray(stored))
        latest = stored;
    } catch {}
    const next = { ...latest, [key]: { ...latest[key], [field]: !current } };
    setPreferences(next);
    try {
      localStorage.setItem("bridge-project-preferences", JSON.stringify(next));
    } catch {}
  }
  const [allTasks, setAllTasks] = useState(false);
  function openContent(path: string) {
    setContentPath(path);
    setView("content");
  }
  const [selected, setSelected] = useState(""),
    [detail, setDetail] = useState<Detail | null>(null),
    [detailError, setDetailError] = useState(""),
    [tab, setTab] = useState("output");
  const [dark, setDark] = useState(() => {
    try {
      return localStorage.getItem("bridge-theme-flight") !== "light";
    } catch {
      return false;
    }
  });
  const request = useRef<{ body: string; id: string } | null>(null);
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    try {
      localStorage.setItem("bridge-theme-flight", dark ? "dark" : "light");
    } catch {}
  }, [dark]);
  async function api<T>(url: string, body?: unknown): Promise<T> {
    const response = await fetch(url, {
      credentials: "same-origin",
      headers: { "X-Bridge-ID": bridgeId },
      ...(body === undefined
        ? {}
        : {
            method: "POST",
            headers: {
              "X-Bridge-ID": bridgeId,
              "Content-Type": "application/json",
              "X-Bridge-CSRF": data?.csrf || "",
            },
            body: JSON.stringify(body),
          }),
    });
    const value = await response.json();
    if (!response.ok)
      throw Object.assign(
        new Error(value.error || `Request failed (${response.status})`),
        { status: response.status },
      );
    return value;
  }
  useEffect(() => {
    let stopped = false;
    async function load() {
      try {
        const value = await api<Bootstrap>("/api/bootstrap");
        if (stopped) return;
        setData(value);
        updateBridges(value.bridges || [value.bridge]);
        try {
          if (
            !languagePreference.current &&
            value.bridge.language?.startsWith("de")
          )
            setLocale("de");
        } catch {}
        setRuns(value.runs);
        setOnline(true);
        setProject(value.projects.find((p) => p.available)?.id || "");
        setClient(value.clients.find((c) => c.available)?.id || "codex");
      } catch (e) {
        if (!stopped) {
          if (
            bridgeId &&
            [400, 404].includes((e as Error & { status?: number }).status || 0)
          ) {
            chooseBridge("", true);
            return;
          }
          setError(String((e as Error).message));
          setOnline(false);
        }
      }
    }
    void load();
    return () => {
      stopped = true;
    };
  }, []);
  useEffect(() => {
    if (!data) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const value = await api<{ runs: Run[] }>("/api/runs");
        if (!stopped) {
          setRuns(value.runs);
          setOnline(true);
        }
      } catch {
        if (!stopped) setOnline(false);
      }
      if (!stopped) timer = setTimeout(poll, 2000);
    }
    timer = setTimeout(poll, 2000);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [data]);
  useEffect(() => {
    setDetail(null);
    setDetailError("");
    if (!selected) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    async function load() {
      try {
        const value = await api<Detail>(
          `/api/runs/${encodeURIComponent(selected)}`,
        );
        if (!stopped) {
          setDetail(value);
          setDetailError("");
        }
      } catch (e) {
        if (!stopped) setDetailError((e as Error).message);
      }
      if (!stopped) timer = setTimeout(load, 2000);
    }
    void load();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [selected]);
  async function start(e: React.FormEvent) {
    e.preventDefault();
    if (pending || !data || data.bridge.read_only || !currentProject) return;
    setPending(true);
    setError("");
    const body = {
      project_id: project,
      client,
      prompt,
      mode,
      trust: client === "vibe" && trust,
    };
    const serialized = JSON.stringify(body);
    if (request.current?.body !== serialized)
      request.current = { body: serialized, id: crypto.randomUUID() };
    try {
      const value = await api<{ run: Run }>("/api/runs", {
        ...body,
        request_id: request.current.id,
      });
      setRuns((previous) => [
        value.run,
        ...previous.filter((r) => r.id !== value.run.id),
      ]);
      setSelected(value.run.id);
      setView("runs");
      request.current = null;
      setPrompt("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPending(false);
    }
  }
  async function cancel() {
    if (!selected || cancelling || data?.bridge.read_only) return;
    setCancelling(true);
    setError("");
    try {
      const value = await api<{ run: Run }>(
        `/api/runs/${encodeURIComponent(selected)}/cancel`,
        {},
      );
      setRuns((previous) =>
        previous.map((r) => (r.id === value.run.id ? value.run : r)),
      );
      setDetail((previous) =>
        previous && previous.run.id === value.run.id
          ? { ...previous, run: value.run }
          : previous,
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setCancelling(false);
    }
  }
  function openRun(run: Run) {
    setSelected(run.id);
    setView("runs");
    setTab("output");
  }
  const shownProjects = (data?.projects || [])
    .filter((p) => {
      const pref = preferences[projectKey(p.id)];
      const archived = pref?.archived ?? p.archived;
      return (
        `${p.name} ${p.path}`.toLowerCase().includes(search.toLowerCase()) &&
        (projectFilter === "all" ||
          (projectFilter === "archived"
            ? archived
            : !archived &&
              (projectFilter === "favorites" ? pref?.favorite : p.available)))
      );
    })
    .sort(
      (a, b) =>
        Number(!!preferences[projectKey(b.id)]?.favorite) -
          Number(!!preferences[projectKey(a.id)]?.favorite) ||
        Number(b.id === "bridge") - Number(a.id === "bridge") ||
        a.name.localeCompare(b.name),
    );
  const readOnly = data?.bridge.read_only === true;
  const currentProject = data?.projects.find(
      (p) =>
        p.id === project &&
        p.available &&
        !(preferences[projectKey(p.id)]?.archived ?? p.archived),
    ),
    availableClient = data?.clients.find((c) => c.id === client)?.available;
  const runList = (items: Run[]) =>
    items.length ? (
      <div className="run-list">
        {items.map((r) => (
          <button
            className={`run-row ${selected === r.id ? "selected" : ""}`}
            key={r.id}
            onClick={() => openRun(r)}
          >
            <span className={`status-dot ${r.status}`} />
            <span className="run-info">
              <strong>{r.project_name}</strong>
              <span>{r.prompt}</span>
            </span>
            <span className="run-meta">
              <span>{statusLabels()[r.status] || r.status}</span>
              <small>
                {date(r.created_at)} · {r.client === "vibe" ? "Vibe" : "Codex"}
              </small>
            </span>
            <Icon name="arrow" />
          </button>
        ))}
      </div>
    ) : (
      <div className="empty">
        <Icon name="play" />
        <h3>{t("no_runs_yet")}</h3>
        <p>{t("choose_a_project_and_describe_your_first_task")}</p>
        {!readOnly && (
          <button className="secondary" onClick={() => setView("compose")}>
            {t("create_a_task")}
          </button>
        )}
      </div>
    );
  return (
    <div className={`app command-console view-${view}`}>
      <a className="skip-link" href="#main">
        {t("skip_to_content")}
      </a>
      <aside className="sidebar">
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setView("overview");
          }}
        >
          <img
            className="brand-logo"
            src="/openbridge-mark.png"
            alt=""
            width="40"
            height="40"
          />
          <span>
            Open<b>Bridge</b>
            <small>{t("your_local_workspace")}</small>
          </span>
        </a>
        <nav aria-label={t("main_navigation")}>
          {[
            ["overview", "grid", t("overview")],
            ["compose", "play", t("new_task")],
            ["runs", "folder", t("runs")],
            ["content", "folder", t("content")],
          ]
            .filter(([id]) => !readOnly || !["compose", "runs"].includes(id))
            .map(([id, icon, label]) => (
              <button
                key={id}
                className={view === id ? "nav-active" : ""}
                onClick={() => setView(id)}
                aria-current={view === id ? "page" : undefined}
              >
                <Icon name={icon} />
                {label}
                {id === "runs" && runs.filter(active).length > 0 && (
                  <span className="count">{runs.filter(active).length}</span>
                )}
              </button>
            ))}
        </nav>
        <div className="sidebar-note">
          <span className="eyebrow">{t("your_files_stay_yours")}</span>
          <p>
            {t(
              "projects_and_tasks_from_markdown_and_yaml_right_in_your_workspace",
            )}
          </p>
        </div>
        <button className="theme" onClick={() => setDark(!dark)}>
          <Icon name="moon" />
          {dark ? t("light_theme") : t("dark_theme")}
        </button>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <button
            className="language-toggle"
            onClick={() => setLocale(locale === "en" ? "de" : "en")}
            aria-label="Language / Sprache"
          >
            {locale.toUpperCase()} ↔ {locale === "en" ? "DE" : "EN"}
          </button>
          <div className="bridge-picker">
            <label htmlFor="bridge-select">{t("choose_bridge")}</label>
            <select
              id="bridge-select"
              value={bridgeId || data?.bridge.id || ""}
              onChange={(event) => chooseBridge(event.target.value)}
              disabled={!bridges.length}
            >
              {!bridges.length && (
                <option value={bridgeId}>{t("loading_bridges")}</option>
              )}
              {bridges.map((bridge) => (
                <option key={bridge.id} value={bridge.id}>
                  {bridge.name.includes(" ")
                    ? bridge.name
                    : bridge.root.split("/").filter(Boolean).pop()}
                  {bridges.filter(
                    (item) =>
                      item.root.split("/").pop() ===
                      bridge.root.split("/").pop(),
                  ).length > 1
                    ? ` · ${bridge.root.split("/").slice(-2, -1)[0]}`
                    : ""}
                </option>
              ))}
            </select>
            <span className="bridge-root" title={data?.bridge.root}>
              {data?.bridge.root ||
                bridges.find((bridge) => bridge.id === bridgeId)?.root ||
                ""}
            </span>
          </div>
          <span className={`connection ${online ? "online" : ""}`}>
            <span className="status-dot" />
            {online ? t("connected_locally") : t("service_disconnected")}
          </span>
        </header>
        <main id="main" tabIndex={-1}>
          {selectionNotice && (
            <p className="alert" role="status">
              {t("bridge_unavailable_fallback")}
            </p>
          )}
          {readOnly && (
            <p className="readonly-notice" role="status">
              <strong>{t("read_only_bridge")}</strong>{" "}
              {t("read_only_bridge_description")}
            </p>
          )}
          {error && (
            <div className="alert" role="alert">
              <span>{error}</span>
              <button
                aria-label={t("dismiss_error")}
                onClick={() => setError("")}
              >
                ×
              </button>
            </div>
          )}
          {!data ? (
            <div className="empty">
              <h1>{error ? t("unable_to_connect") : t("loading_workspace")}</h1>
              <p>
                {error
                  ? t("check_that_the_local_bridge_service_is_running")
                  : t("reading_projects_tasks_and_runs")}
              </p>
              {error && (
                <button className="secondary" onClick={() => location.reload()}>
                  {t("reconnect")}
                </button>
              )}
            </div>
          ) : (
            <>
              <div
                className={`page-heading ${view === "overview" ? "overview-heading" : ""}`}
              >
                <div>
                  <span className="eyebrow">
                    OPEN BRIDGE /{" "}
                    {view === "compose"
                      ? t("task")
                      : view === "content"
                        ? t("content")
                        : view === "runs"
                          ? t("runs")
                          : t("overview")}
                  </span>
                  <h1>
                    {view === "compose"
                      ? t("what_will_you_move_forward")
                      : view === "content"
                        ? t("content_heading")
                        : view === "runs"
                          ? t("follow_the_work")
                          : t("everything_in_one_place")}
                  </h1>
                  <p>
                    {view === "compose"
                      ? t("one_project_a_clear_goal_and_the_right_cli")
                      : view === "content"
                        ? t("content_subtitle")
                        : view === "runs"
                          ? t("track_progress_read_results_and_review_changes")
                          : t("from_your_projects_to_the_next_meaningful_step")}
                  </p>
                </div>
                {view === "overview" && !readOnly && (
                  <button
                    className="primary"
                    onClick={() => setView("compose")}
                  >
                    {t("new_task")}
                    <Icon name="arrow" />
                  </button>
                )}
              </div>
              {view === "overview" && (
                <div className="command-layout">
                  <section
                    className={`forward-viewport ${scenePaused ? "scene-paused" : ""}`}
                    aria-label={t("forward_display")}
                  >
                    <div className="planet-window" aria-hidden="true" />
                    <div className="viewport-topline">
                      <span>OPENBRIDGE / {t("command_deck")}</span>
                      <span className="viewport-link">
                        <span
                          className={`status-dot ${online ? "succeeded" : "interrupted"}`}
                        />
                        {online
                          ? t("connected_locally")
                          : t("service_disconnected")}
                      </span>
                    </div>
                    <div className="viewport-copy">
                      <span className="viewport-designation">
                        {data.bridge.root.split("/").filter(Boolean).pop()}
                      </span>
                      <h1>{t("everything_in_one_place")}</h1>
                      <p>{t("viewport_description")}</p>
                      <div className="viewport-actions">
                        {!readOnly && (
                          <button
                            className="primary"
                            onClick={() => setView("compose")}
                          >
                            {t("new_task")}
                            <Icon name="arrow" />
                          </button>
                        )}
                        <button
                          className="secondary"
                          onClick={() => setView("content")}
                        >
                          {t("content")}
                          <Icon name="folder" />
                        </button>
                      </div>
                    </div>
                    <div className="viewport-bottomline">
                      <span>{t("local_workspace")}</span>
                      <span>MARKDOWN / YAML</span>
                      <button
                        className="scene-motion"
                        aria-pressed={scenePaused}
                        onClick={toggleScene}
                      >
                        {t(scenePaused ? "resume_scene" : "pause_scene")}
                      </button>
                    </div>
                  </section>
                  <aside
                    className="systems-console"
                    aria-label={t("systems_panel")}
                  >
                    <div className="console-label">
                      <span>01 / {t("systems_panel")}</span>
                      <span className="instrument-light" />
                    </div>
                    <div className="bridge-instrument">
                      <svg viewBox="0 0 180 180" aria-hidden="true">
                        <circle cx="90" cy="90" r="78" />
                        <circle cx="90" cy="90" r="68" />
                        <path d="M90 4v12M90 164v12M4 90h12M164 90h12" />
                      </svg>
                      <div>
                        <strong>
                          {bridges.length.toString().padStart(2, "0")}
                        </strong>
                        <span>{t("registered_bridges")}</span>
                      </div>
                    </div>
                    <div className="station-list">
                      {bridges.map((bridge, index) => (
                        <button
                          key={bridge.id}
                          aria-pressed={bridge.id === data.bridge.id}
                          onClick={() => chooseBridge(bridge.id)}
                          title={bridge.root}
                        >
                          <span className="station-index">
                            {String(index + 1).padStart(2, "0")}
                          </span>
                          <span>
                            {bridge.root.split("/").filter(Boolean).pop()}
                          </span>
                          <span className="station-led" />
                        </button>
                      ))}
                    </div>
                    <div
                      className={`stats ${readOnly ? "stats-readonly" : ""}`}
                    >
                      <div>
                        <strong>
                          {
                            data.projects.filter(
                              (p) =>
                                p.available &&
                                !(
                                  preferences[projectKey(p.id)]?.archived ??
                                  p.archived
                                ),
                            ).length
                          }
                        </strong>
                        <span>{t("available_projects")}</span>
                      </div>
                      <div>
                        <strong>
                          {data.tasks.filter((t) => t.status !== "done").length}
                        </strong>
                        <span>{t("open_tasks")}</span>
                      </div>
                      {!readOnly && (
                        <div>
                          <strong>{runs.filter(active).length}</strong>
                          <span>{t("active_runs")}</span>
                        </div>
                      )}
                    </div>
                    <div className="console-footnote">
                      {t("local_files_notice")}
                    </div>
                  </aside>
                  <section className="projects-console">
                    <div className="console-label">
                      <span>02 / {t("project_registry")}</span>
                      <span>
                        {shownProjects.length} {t("projects")}
                      </span>
                    </div>
                    <div className="section-heading">
                      <h2>{t("your_projects")}</h2>
                      <label className="search">
                        <Icon name="search" />
                        <input
                          aria-label={t("search_projects")}
                          placeholder={t("search_projects")}
                          value={search}
                          onChange={(e) => setSearch(e.target.value)}
                        />
                      </label>
                    </div>
                    <div className="project-tools">
                      <label>
                        {t("project_filter")}{" "}
                        <select
                          value={projectFilter}
                          onChange={(e) => {
                            setProjectFilter(e.target.value);
                            setAllProjects(false);
                          }}
                        >
                          <option value="available">
                            {t("available_projects")}
                          </option>
                          <option value="favorites">{t("favorites")}</option>
                          <option value="archived">
                            {t("archived_projects")}
                          </option>
                          <option value="all">{t("all_projects")}</option>
                        </select>
                      </label>
                      <p className="field-note">
                        {t("project_preferences_note")}
                      </p>
                    </div>
                    <div className="project-grid">
                      {shownProjects
                        .slice(0, allProjects ? undefined : 12)
                        .map((p) => (
                          <article className="project-tile" key={p.id}>
                            <button
                              className="project-card"
                              disabled={
                                !p.available ||
                                readOnly ||
                                !!(
                                  preferences[projectKey(p.id)]?.archived ??
                                  p.archived
                                )
                              }
                              onClick={() => {
                                setProject(p.id);
                                setView("compose");
                              }}
                            >
                              <span className="project-icon">
                                <Icon name="folder" />
                              </span>
                              <strong>{p.name}</strong>
                              <span className="project-path" title={p.path}>
                                {p.path}
                              </span>
                              <span className="project-footer">
                                {readOnly
                                  ? t("read_only_bridge")
                                  : (preferences[projectKey(p.id)]?.archived ??
                                      p.archived)
                                    ? t("archived_projects")
                                    : p.available
                                      ? t("create_a_task")
                                      : t("path_unavailable")}
                                <Icon name="arrow" />
                              </span>
                            </button>
                            <div className="project-controls">
                              <button
                                className="text-button"
                                aria-pressed={
                                  !!preferences[projectKey(p.id)]?.favorite
                                }
                                onClick={() =>
                                  prefer(
                                    p.id,
                                    "favorite",
                                    !!preferences[projectKey(p.id)]?.favorite,
                                  )
                                }
                              >
                                {preferences[projectKey(p.id)]?.favorite
                                  ? "★"
                                  : "☆"}{" "}
                                {t("favorite_project")}
                              </button>
                              <button
                                className="text-button"
                                onClick={() =>
                                  prefer(
                                    p.id,
                                    "archived",
                                    !!(
                                      preferences[projectKey(p.id)]?.archived ??
                                      p.archived
                                    ),
                                  )
                                }
                              >
                                {t(
                                  (preferences[projectKey(p.id)]?.archived ??
                                    p.archived)
                                    ? "restore_project"
                                    : "archive_project",
                                )}
                              </button>
                            </div>
                          </article>
                        ))}
                    </div>
                    {!shownProjects.length && (
                      <p className="muted">
                        {search
                          ? t("no_matching_projects_found")
                          : t(
                              "no_projects_available_yet_register_projects_in_ecosystem_yaml",
                            )}
                      </p>
                    )}
                    {shownProjects.length > 12 && (
                      <div className="list-expansion">
                        <span className="muted">
                          {allProjects ? shownProjects.length : 12} /{" "}
                          {shownProjects.length}
                        </span>
                        <button
                          className="secondary"
                          onClick={() => setAllProjects(!allProjects)}
                        >
                          {t(
                            allProjects
                              ? "show_fewer_projects"
                              : "show_all_projects",
                          )}
                        </button>
                      </div>
                    )}
                  </section>
                  {!readOnly && (
                    <section className="runs-console">
                      <div className="console-label">
                        <span>04 / {t("execution_log")}</span>
                      </div>
                      <div className="section-heading">
                        <h2>{t("recent_runs")}</h2>
                        <button
                          className="text-button"
                          onClick={() => setView("runs")}
                        >
                          {t("view_all")}
                          <Icon name="arrow" />
                        </button>
                      </div>
                      {runList(runs.slice(0, 4))}
                    </section>
                  )}
                  <section className="tasks-console">
                    <div className="console-label">
                      <span>03 / {t("mission_queue")}</span>
                      <span>
                        {data.tasks.length.toString().padStart(2, "0")}
                      </span>
                    </div>
                    <div className="section-heading">
                      <h2>{t("tasks_at_a_glance")}</h2>
                      <span className="muted">{t("from_your_work_board")}</span>
                    </div>
                    {data.tasks.length ? (
                      <div className="tasks">
                        {data.tasks
                          .slice(0, allTasks ? undefined : 8)
                          .map((t) => (
                            <button
                              className="task task-link"
                              key={t.id}
                              onClick={() =>
                                openContent(t.path || `work/${t.id}/STATUS.md`)
                              }
                            >
                              <Icon name="check" />
                              <span>
                                <strong>{t.title}</strong>
                                {t.context && <small>{t.context}</small>}
                              </span>
                              <span className="badge">
                                {statusLabels()[t.status] || t.status}
                              </span>
                            </button>
                          ))}
                      </div>
                    ) : (
                      <p className="muted">
                        {t("no_tasks_in_the_work_board_yet")}
                      </p>
                    )}
                    {data.tasks.length > 8 && (
                      <div className="list-expansion">
                        <span className="muted">
                          {allTasks ? data.tasks.length : 8} /{" "}
                          {data.tasks.length}
                        </span>
                        <button
                          className="secondary"
                          onClick={() => setAllTasks(!allTasks)}
                        >
                          {t(allTasks ? "show_fewer_tasks" : "show_all_tasks")}
                        </button>
                      </div>
                    )}
                  </section>
                </div>
              )}
              {view === "content" && (
                <React.Suspense
                  fallback={<p role="status">{t("loading_content")}</p>}
                >
                  <ContentBrowser
                    bridgeId={bridgeId}
                    csrf={data.csrf}
                    contentEditable={data.bridge.content_editable === true}
                    onEditorState={reportEditor}
                    initialPath={contentPath}
                    translate={(key) => t(key as keyof typeof english)}
                  />
                </React.Suspense>
              )}
              {view === "compose" && !readOnly && (
                <form className="composer" onSubmit={start}>
                  <div className="form-section">
                    <span className="step">01</span>
                    <div>
                      <h2>{t("choose_your_workspace")}</h2>
                      <label htmlFor="project">{t("project")}</label>
                      <select
                        id="project"
                        value={currentProject ? project : ""}
                        onChange={(e) => setProject(e.target.value)}
                        required
                      >
                        <option value="" disabled>
                          {t("choose_a_project")}
                        </option>
                        {data.projects
                          .filter(
                            (p) =>
                              p.available &&
                              !(
                                preferences[projectKey(p.id)]?.archived ??
                                p.archived
                              ),
                          )
                          .map((p) => (
                            <option
                              key={p.id}
                              value={p.id}
                              disabled={!p.available || readOnly}
                            >
                              {p.name}
                              {!p.available ? t("unavailable") : ""}
                            </option>
                          ))}
                      </select>
                      {currentProject && (
                        <p className="field-note path">{currentProject.path}</p>
                      )}
                      <fieldset>
                        <legend>CLI</legend>
                        <div className="client-options">
                          {["codex", "vibe"].map((id) => (
                            <label
                              className={`client-option ${client === id ? "chosen" : ""}`}
                              key={id}
                            >
                              <input
                                type="radio"
                                name="client"
                                value={id}
                                checked={client === id}
                                disabled={
                                  !data.clients.find((c) => c.id === id)
                                    ?.available
                                }
                                onChange={() => setClient(id)}
                              />
                              <span>
                                <strong>
                                  {id === "codex"
                                    ? "Codex CLI"
                                    : "Mistral Vibe CLI"}
                                </strong>
                                <small>
                                  {data.clients.find((c) => c.id === id)
                                    ?.available
                                    ? t("installed_locally")
                                    : t("not_installed")}
                                </small>
                              </span>
                            </label>
                          ))}
                        </div>
                      </fieldset>
                    </div>
                  </div>
                  <div className="form-section">
                    <span className="step">02</span>
                    <div>
                      <h2>{t("describe_your_goal")}</h2>
                      <label htmlFor="prompt">
                        {t("what_should_bridge_do")}
                      </label>
                      <textarea
                        id="prompt"
                        rows={6}
                        required
                        minLength={3}
                        maxLength={20000}
                        value={prompt}
                        onChange={(e) => setPrompt(e.target.value)}
                        placeholder={t(
                          "for_example_review_error_handling_and_explain_which_improvements_are_needed",
                        )}
                      />
                      <p className="field-note">
                        {t(
                          "describe_the_desired_outcome_and_important_constraints",
                        )}
                      </p>
                      <fieldset>
                        <legend>{t("working_mode")}</legend>
                        <label className="mode-option">
                          <input
                            type="radio"
                            name="mode"
                            checked={mode === "inspect"}
                            onChange={() => setMode("inspect")}
                          />
                          <span>
                            <strong>{t("inspect")}</strong>
                            <small>
                              {t(
                                "analysis_with_restricted_tools_no_planned_file_changes",
                              )}
                            </small>
                          </span>
                        </label>
                        <label className="mode-option">
                          <input
                            type="radio"
                            name="mode"
                            checked={mode === "edit"}
                            onChange={() => setMode("edit")}
                          />
                          <span>
                            <strong>{t("edit")}</strong>
                            <small>
                              {t(
                                "the_cli_may_change_project_files_review_the_results_afterwards",
                              )}
                            </small>
                          </span>
                        </label>
                      </fieldset>
                      {client === "vibe" && (
                        <label className="trust">
                          <input
                            type="checkbox"
                            checked={trust}
                            onChange={(e) => setTrust(e.target.checked)}
                          />
                          <span>
                            {t("trust_this_project_for_this_vibe_invocation")}
                            <small>
                              {t(
                                "enable_only_if_you_trust_the_project_s_contents",
                              )}
                            </small>
                          </span>
                        </label>
                      )}
                    </div>
                  </div>
                  <div className="form-footer">
                    <p>
                      {t(
                        "the_task_continues_in_the_local_service_if_you_reload_your_browser_the_cli_may_contact_its_ai_provider",
                      )}
                    </p>
                    <button
                      className="primary"
                      disabled={
                        pending ||
                        !online ||
                        !currentProject ||
                        !availableClient ||
                        prompt.trim().length < 3
                      }
                    >
                      {pending ? t("starting") : t("start_task")}
                      <Icon name="arrow" />
                    </button>
                  </div>
                </form>
              )}
              {view === "runs" && (
                <div
                  className={`execution-layout ${selected ? "with-detail" : ""}`}
                >
                  <section className="all-runs">
                    <h2>
                      {t("runs")}
                      <span className="muted">{runs.length}</span>
                    </h2>
                    {runList(runs)}
                  </section>
                  {selected && (
                    <section className="detail">
                      <div className="section-heading">
                        <h2>{t("result")}</h2>
                        <button
                          className="text-button"
                          onClick={() => setSelected("")}
                        >
                          {t("close")}
                        </button>
                      </div>
                      {detailError ? (
                        <p role="alert" className="alert">
                          {detailError}
                        </p>
                      ) : !detail ? (
                        <p className="muted">{t("loading_run")}</p>
                      ) : (
                        <>
                          <div className="detail-heading">
                            <span className="badge">
                              <span
                                className={`status-dot ${detail.run.status}`}
                              />
                              {statusLabels()[detail.run.status] ||
                                detail.run.status}
                            </span>
                            <span className="muted">
                              {detail.run.client} ·{" "}
                              {detail.run.mode === "edit"
                                ? t("edit")
                                : t("inspect")}
                            </span>
                            {active(detail.run) && !readOnly && (
                              <button
                                className="secondary"
                                disabled={cancelling || !online}
                                onClick={cancel}
                              >
                                {cancelling
                                  ? t("requesting_cancellation")
                                  : t("cancel")}
                              </button>
                            )}
                          </div>
                          <h3>{detail.run.project_name}</h3>
                          <p className="run-prompt">{detail.run.prompt}</p>
                          {detail.run.error && (
                            <p className="alert" role="alert">
                              {detail.run.error}
                            </p>
                          )}
                          <div
                            className="tabs"
                            role="tablist"
                            aria-label={t("run_details")}
                          >
                            {[
                              ["output", t("output")],
                              ["review", t("review_changes")],
                            ].map(([id, title]) => (
                              <button
                                role="tab"
                                aria-selected={tab === id}
                                tabIndex={tab === id ? 0 : -1}
                                onKeyDown={(event) => {
                                  if (
                                    [
                                      "ArrowLeft",
                                      "ArrowRight",
                                      "Home",
                                      "End",
                                    ].includes(event.key)
                                  ) {
                                    event.preventDefault();
                                    const next =
                                      event.key === "Home"
                                        ? "output"
                                        : event.key === "End"
                                          ? "review"
                                          : tab === "output"
                                            ? "review"
                                            : "output";
                                    setTab(next);
                                    document
                                      .getElementById(`tab-${next}`)
                                      ?.focus();
                                  }
                                }}
                                aria-controls={`panel-${id}`}
                                id={`tab-${id}`}
                                key={id}
                                onClick={() => setTab(id)}
                              >
                                {title}
                              </button>
                            ))}
                          </div>
                          {tab === "output" ? (
                            <div
                              id="panel-output"
                              role="tabpanel"
                              aria-labelledby="tab-output"
                            >
                              <h4>{t("standard_output")}</h4>
                              <pre>{detail.stdout || t("no_output_yet")}</pre>
                              {detail.stderr && (
                                <>
                                  <h4>{t("diagnostic_output")}</h4>
                                  <pre>{detail.stderr}</pre>
                                </>
                              )}
                              {detail.run.exit_code !== null && (
                                <p className="field-note">
                                  {t("exit_code")}
                                  {detail.run.exit_code}
                                </p>
                              )}
                            </div>
                          ) : (
                            <div
                              id="panel-review"
                              role="tabpanel"
                              aria-labelledby="tab-review"
                            >
                              <p className="field-note">
                                Branch:{" "}
                                <strong>
                                  {detail.review.branch || t("unavailable")}
                                </strong>{" "}
                                ·{" "}
                                {detail.review.dirty
                                  ? t("local_changes_present")
                                  : t("working_tree_clean")}
                              </p>
                              <p className="field-note">
                                {t(
                                  "this_view_shows_the_current_git_working_tree_changes_may_predate_this_task",
                                )}
                              </p>
                              {detail.changed_files.length > 0 && (
                                <ul className="changed-files">
                                  {detail.changed_files.map((f, i) => (
                                    <li key={`${f.path}-${i}`}>
                                      <code>{f.status}</code>
                                      <span>{f.path}</span>
                                    </li>
                                  ))}
                                </ul>
                              )}
                              <pre>
                                {detail.diff ||
                                  t("no_displayable_git_differences")}
                              </pre>
                              <p className="field-note">
                                {t(
                                  "publishing_and_pull_requests_remain_part_of_your_reviewed_cli_workflow",
                                )}
                              </p>
                            </div>
                          )}
                        </>
                      )}
                    </section>
                  )}
                </div>
              )}
            </>
          )}
          <footer>
            <span>{t("open_bridge_local_first")}</span>
            <span>{t("markdown_yaml_remain_the_foundation")}</span>
          </footer>
        </main>
      </div>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BridgeWorkspace />
  </React.StrictMode>,
);
