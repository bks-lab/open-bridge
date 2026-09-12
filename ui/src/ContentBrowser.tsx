import { createElement, useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { diffLines } from "diff";
import { common, createLowlight } from "lowlight";
const syntax = createLowlight(common);

type Entry = {
  path: string;
  category: string;
  size: number;
  line?: number;
  snippet?: string;
};
type Index = {
  entries: Entry[];
  categories: { id: string; count: number }[];
  excluded: string[];
};
type Document = {
  path: string;
  content: string;
  truncated: boolean;
  revision: string | null;
  editable: boolean;
  backup?: string;
  warning?: string;
};
type Props = {
  bridgeId: string;
  csrf: string;
  contentEditable: boolean;
  onEditorState: (state: { dirty: boolean; saving: boolean }) => void;
  initialPath: string;
  translate: (key: string) => string;
};
async function read<T>(url: string, bridgeId: string): Promise<T> {
  const response = await fetch(url, {
    credentials: "same-origin",
    headers: { "X-Bridge-ID": bridgeId },
  });
  const value = await response.json();
  if (!response.ok)
    throw new Error(value.error || `Request failed (${response.status})`);
  return value;
}
export default function ContentBrowser({
  bridgeId,
  csrf,
  contentEditable,
  onEditorState,
  initialPath,
  translate: t,
}: Props) {
  const sessionToken = useRef(csrf);
  const [sessionExpired, setSessionExpired] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const [reconnected, setReconnected] = useState(false);
  useEffect(() => {
    sessionToken.current = csrf;
  }, [csrf]);
  async function reconnect() {
    if (reconnecting) return;
    setReconnecting(true);
    try {
      const response = await fetch("/api/bootstrap", {
        credentials: "same-origin",
        headers: { "X-Bridge-ID": bridgeId },
      });
      const value = await response.json();
      if (!mounted.current) return;
      if (!response.ok || typeof value.csrf !== "string")
        throw new Error(value.error || t("reconnect_failed"));
      sessionToken.current = value.csrf;
      setSessionExpired(false);
      setSaveError("");
      setReconnected(true);
    } catch (reason) {
      if (mounted.current) setSaveError((reason as Error).message);
    } finally {
      if (mounted.current) setReconnecting(false);
    }
  }
  const [display, setDisplay] = useState("preview");
  const [showChanges, setShowChanges] = useState(false);
  const [history, setHistory] = useState<
    { id: string; modified: number; size: number }[] | null
  >(null);
  const [historyBusy, setHistoryBusy] = useState(false);
  const [backupNotice, setBackupNotice] = useState(false);
  const [fulltext, setFulltext] = useState(false);
  const [searchResults, setSearchResults] = useState<{
    entries: Entry[];
    skipped: number;
  } | null>(null);
  const [searchBusy, setSearchBusy] = useState(false);
  const searchGeneration = useRef(0);
  const [recent, setRecent] = useState<string[]>(() => {
    try {
      const value = JSON.parse(
        localStorage.getItem(`bridge-recent:${bridgeId}`) || "[]",
      );
      return Array.isArray(value)
        ? value.filter((x) => typeof x === "string").slice(0, 5)
        : [];
    } catch {
      return [];
    }
  });
  async function searchContents() {
    if (search.trim().length < 2) {
      setError(t("search_minimum"));
      return;
    }
    const generation = ++searchGeneration.current;
    setSearchBusy(true);
    setError("");
    try {
      const result = await read<{ entries: Entry[]; skipped: number }>(
        `/api/content/search?q=${encodeURIComponent(search)}`,
        bridgeId,
      );
      if (mounted.current && generation === searchGeneration.current) {
        setSearchResults(result);
        setPage(0);
      }
    } catch (reason) {
      if (mounted.current && generation === searchGeneration.current)
        setError((reason as Error).message);
    } finally {
      if (mounted.current && generation === searchGeneration.current)
        setSearchBusy(false);
    }
  }
  async function loadHistory() {
    const selectedPath = path;
    setHistoryBusy(true);
    try {
      const value = await read<{
        entries: { id: string; modified: number; size: number }[];
      }>(`/api/content/backups?path=${encodeURIComponent(path)}`, bridgeId);
      if (mounted.current && currentPath.current === selectedPath)
        setHistory(value.entries);
    } catch (reason) {
      if (mounted.current && currentPath.current === selectedPath)
        setSaveError((reason as Error).message);
    } finally {
      if (mounted.current) setHistoryBusy(false);
    }
  }
  async function loadBackup(id: string) {
    if (!mayDiscard()) return;
    const selectedPath = path;
    report(editorState.current.dirty, true);
    setHistoryBusy(true);
    try {
      const value = await read<{ content: string }>(
        `/api/content/backups?path=${encodeURIComponent(path)}&backup=${encodeURIComponent(id)}`,
        bridgeId,
      );
      if (mounted.current && currentPath.current === selectedPath) {
        setDraft(value.content);
        setEditing(true);
        setShowChanges(true);
        setBackupNotice(true);
        report(value.content !== document?.content);
        setHistory(null);
      }
    } catch (reason) {
      if (mounted.current && currentPath.current === selectedPath)
        setSaveError((reason as Error).message);
    } finally {
      if (mounted.current) {
        setHistoryBusy(false);
        report(editorState.current.dirty, false);
      }
    }
  }
  function renderSource(content: string) {
    const language = (
      {
        md: "markdown",
        yaml: "yaml",
        yml: "yaml",
        json: "json",
        py: "python",
        js: "javascript",
        ts: "typescript",
        sh: "bash",
        css: "css",
      } as Record<string, string>
    )[path.split(".").pop() || ""];
    if (!language || content.length > 60000 || !syntax.registered(language))
      return <pre tabIndex={0}>{content}</pre>;
    const tree = syntax.highlight(language, content);
    function render(
      node: (typeof tree.children)[number],
      index: number,
    ): React.ReactNode {
      if (node.type === "text") return node.value;
      if (node.type === "element")
        return createElement(
          "span",
          {
            key: index,
            className: ((node.properties.className as string[]) || []).join(
              " ",
            ),
          },
          node.children.map(render),
        );
      return null;
    }
    return (
      <pre className="syntax-source" tabIndex={0}>
        {tree.children.map(render)}
      </pre>
    );
  }
  function renderMarkdown(content: string) {
    return (
      <div className="markdown-preview">
        <Markdown
          remarkPlugins={[remarkGfm]}
          skipHtml
          components={{
            img: ({ alt }) => (
              <span className="field-note">
                [{t("external_image")}: {alt}]
              </span>
            ),
            a: ({ href, children }) =>
              /^https?:\/\//.test(href || "") ? (
                <a href={href} target="_blank" rel="noreferrer noopener">
                  {children}
                </a>
              ) : (
                <span>{children}</span>
              ),
          }}
        >
          {content}
        </Markdown>
      </div>
    );
  }
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [conflict, setConflict] = useState(false);
  const [saved, setSaved] = useState(false);
  const editorState = useRef({ dirty: false, saving: false });
  const mounted = useRef(true);
  function report(dirty: boolean, inFlight = false) {
    editorState.current = { dirty, saving: inFlight };
    onEditorState(editorState.current);
  }
  function mayDiscard() {
    return (
      !editorState.current.saving &&
      (!editorState.current.dirty ||
        window.confirm(t("discard_unsaved_changes")))
    );
  }
  function resetEditor() {
    setEditing(false);
    setHistory(null);
    setBackupNotice(false);
    setShowChanges(false);
    setSaveError("");
    setConflict(false);
    setSaved(false);
    setReconnected(false);
    report(false);
  }
  function selectFile(next: string) {
    if (next !== path && mayDiscard()) {
      resetEditor();
      setPath(next);
      if (next) {
        const value = [next, ...recent.filter((item) => item !== next)].slice(
          0,
          5,
        );
        setRecent(value);
        try {
          localStorage.setItem(
            `bridge-recent:${bridgeId}`,
            JSON.stringify(value),
          );
        } catch {}
      }
    }
  }
  function refreshFiles() {
    if (mayDiscard()) {
      resetEditor();
      setRefresh((value) => value + 1);
    }
  }
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      onEditorState({ dirty: false, saving: false });
    };
  }, [onEditorState]);
  async function save() {
    if (
      !document ||
      editorState.current.saving ||
      !editing ||
      !document.editable ||
      typeof document.revision !== "string" ||
      document.truncated ||
      conflict ||
      sessionExpired
    )
      return;
    const snapshot = {
      path: document.path,
      content: draft,
      revision: document.revision,
    };
    report(draft !== document.content, true);
    setReconnected(false);
    setSaving(true);
    setSaveError("");
    setSaved(false);
    try {
      const response = await fetch("/api/content", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-Bridge-ID": bridgeId,
          "X-Bridge-CSRF": sessionToken.current,
        },
        body: JSON.stringify(snapshot),
      });
      const value = await response.json();
      if (!mounted.current) return;
      if (!response.ok) {
        setConflict(response.status === 409);
        setSessionExpired(response.status === 403);
        const codes: Record<string, string> = {
          conflict: "save_conflict",
          invalid_syntax: "save_invalid_syntax",
          not_editable: "file_not_editable",
          invalid_path: "save_invalid_path",
          too_large: "save_too_large",
          save_failed: "save_failed",
        };
        throw new Error(
          codes[value.code]
            ? t(codes[value.code])
            : value.error || `Request failed (${response.status})`,
        );
      }
      setDocument(value);
      setDraft(value.content);
      setEditing(false);
      setSaved(true);
      report(false);
    } catch (reason) {
      if (mounted.current) setSaveError((reason as Error).message);
    } finally {
      if (mounted.current) {
        setSaving(false);
        report(editorState.current.dirty, false);
      }
    }
  }
  const [index, setIndex] = useState<Index | null>(null);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [page, setPage] = useState(0);
  const [path, setPath] = useState(initialPath);
  const currentPath = useRef(path);
  currentPath.current = path;
  const [document, setDocument] = useState<Document | null>(null);
  const [documentError, setDocumentError] = useState("");
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    setPath(initialPath);
  }, [initialPath]);
  useEffect(() => {
    let cancelled = false;
    setError("");
    read<Index>("/api/content", bridgeId)
      .then((value) => {
        if (!cancelled) setIndex(value);
      })
      .catch((reason) => {
        if (!cancelled) setError(reason.message);
      });
    return () => {
      cancelled = true;
    };
  }, [refresh, bridgeId]);
  useEffect(() => {
    setDocument(null);
    setDocumentError("");
    if (!path) return;
    let cancelled = false;
    read<Document>(`/api/content?path=${encodeURIComponent(path)}`, bridgeId)
      .then((value) => {
        if (!cancelled) setDocument(value);
      })
      .catch((reason) => {
        if (!cancelled) setDocumentError(reason.message);
      });
    return () => {
      cancelled = true;
    };
  }, [path, refresh, bridgeId]);
  function warningText(value: string) {
    const messages = [];
    if (value.includes("work-log")) messages.push(t("saved_log_warning"));
    if (value.includes("durability"))
      messages.push(t("saved_durability_warning"));
    return messages.length ? messages.join(" ") : t("saved_warning");
  }
  function categoryName(category: string) {
    const known = [
      "root",
      "docs",
      "work",
      "rules",
      "protocols",
      "skills",
      "identity",
      "infra",
      "workflow",
      "scripts",
      "themes",
      "trackers",
      "agents",
      ".claude",
      "ui",
      "bin",
      "examples",
    ];
    return known.includes(category)
      ? t(`category_${category.replace(".", "")}`)
      : category;
  }
  function exclusionText(reason: string) {
    if (reason.startsWith("Only local canonical")) return t("exclusion_local");
    if (reason.startsWith("Symlinks, hidden")) return t("exclusion_hidden");
    if (reason.startsWith("Credential, secret"))
      return t("exclusion_credentials");
    if (reason.startsWith("Binary files, generated"))
      return t("exclusion_binary");
    if (reason.startsWith("Document previews")) return t("exclusion_preview");
    return reason;
  }
  const matches =
    (fulltext ? searchResults?.entries : index?.entries)?.filter(
      (entry) =>
        (!category || entry.category === category) &&
        (fulltext ||
          entry.path.toLocaleLowerCase().includes(search.toLocaleLowerCase())),
    ) || [];
  const pageSize = 60;
  const lastPage = Math.max(0, Math.ceil(matches.length / pageSize) - 1);
  const currentPage = Math.min(page, lastPage);
  return (
    <section className="content-browser">
      <div className="content-intro">
        <p>{t("content_readonly_description")}</p>
        <button
          className="secondary"
          disabled={saving || historyBusy}
          onClick={refreshFiles}
        >
          {t("refresh_content")}
        </button>
      </div>
      {error && (
        <div className="alert" role="alert">
          {error}
        </div>
      )}
      {!index && !error ? (
        <p role="status">{t("loading_content")}</p>
      ) : (
        index && (
          <>
            <div className="content-filters">
              <label>
                {t("search_content")}
                <input
                  value={search}
                  onChange={(event) => {
                    setSearch(event.target.value);
                    searchGeneration.current++;
                    setSearchBusy(false);
                    setSearchResults(null);
                    setPage(0);
                  }}
                  placeholder={t("search_content_placeholder")}
                />
              </label>
              <label>
                {t("content_category")}
                <select
                  aria-label={t("content_category")}
                  value={category}
                  onChange={(event) => {
                    setCategory(event.target.value);
                    setPage(0);
                  }}
                >
                  <option value="">
                    {t("all_categories")} ({index.entries.length})
                  </option>
                  {index.categories.map((item) => (
                    <option value={item.id} key={item.id}>
                      {categoryName(item.id)} ({item.count})
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="search-options">
              <label>
                <input
                  type="checkbox"
                  checked={fulltext}
                  onChange={(e) => {
                    setFulltext(e.target.checked);
                    setSearchResults(null);
                    searchGeneration.current++;
                    setSearchBusy(false);
                  }}
                />{" "}
                {t("fulltext")}
              </label>
              {fulltext && (
                <>
                  <button
                    className="primary"
                    disabled={searchBusy}
                    onClick={searchContents}
                  >
                    {t(searchBusy ? "searching" : "search_now")}
                  </button>
                  <span className="field-note">{t("search_scope_note")}</span>
                </>
              )}
              {searchResults && searchResults.skipped > 0 && (
                <span role="status">
                  {t("search_skipped")}: {searchResults.skipped}
                </span>
              )}
            </div>
            {recent.length > 0 && (
              <div className="recent-documents">
                <span>{t("recent_documents")}</span>
                {recent
                  .filter((item) =>
                    index.entries.some((entry) => entry.path === item),
                  )
                  .map((item) => (
                    <button
                      className="text-button"
                      disabled={saving || historyBusy}
                      key={item}
                      onClick={() => selectFile(item)}
                    >
                      {item}
                    </button>
                  ))}
              </div>
            )}
            <div className="content-layout">
              <div className="content-file-list">
                <p className="field-note" role="status">
                  {matches.length}{" "}
                  {t(matches.length === 1 ? "matching_file" : "matching_files")}{" "}
                  · {matches.length ? currentPage * pageSize + 1 : 0}–
                  {Math.min((currentPage + 1) * pageSize, matches.length)}
                </p>
                <div className="file-rows">
                  {matches
                    .slice(currentPage * pageSize, (currentPage + 1) * pageSize)
                    .map((entry) => (
                      <button
                        className={`file-row ${path === entry.path ? "selected" : ""}`}
                        key={entry.path}
                        disabled={saving || historyBusy}
                        onClick={() => selectFile(entry.path)}
                        aria-current={path === entry.path ? "true" : undefined}
                      >
                        <strong>{entry.path}</strong>
                        {entry.snippet && (
                          <span className="search-snippet">
                            {t("line_number")} {entry.line}: {entry.snippet}
                          </span>
                        )}
                        <span>
                          {categoryName(entry.category)} ·{" "}
                          {Math.ceil(entry.size / 1024)} KB
                        </span>
                      </button>
                    ))}
                </div>
                {!matches.length && (
                  <p className="muted">{t("no_matching_files")}</p>
                )}
                <div className="pagination">
                  <button
                    className="secondary"
                    disabled={currentPage === 0}
                    onClick={() => setPage(currentPage - 1)}
                  >
                    {t("previous_page")}
                  </button>
                  <span>
                    {currentPage + 1} / {lastPage + 1}
                  </span>
                  <button
                    className="secondary"
                    disabled={currentPage >= lastPage}
                    onClick={() => setPage(currentPage + 1)}
                  >
                    {t("next_page")}
                  </button>
                </div>
              </div>
              <div
                className="content-document"
                aria-label={t("document_viewer")}
              >
                {!path ? (
                  <div className="empty">
                    <h2>{t("choose_document")}</h2>
                    <p>{t("choose_document_description")}</p>
                  </div>
                ) : (
                  <>
                    <div className="section-heading">
                      <h2>{path}</h2>
                      <button
                        className="text-button"
                        disabled={saving || historyBusy}
                        onClick={() => selectFile("")}
                      >
                        {t("close_document")}
                      </button>
                    </div>
                    {documentError ? (
                      <p className="alert" role="alert">
                        {documentError}
                      </p>
                    ) : !document ? (
                      <p role="status">{t("loading_document")}</p>
                    ) : (
                      <>
                        {document.truncated && (
                          <p className="alert" role="status">
                            {t("document_truncated")}
                          </p>
                        )}
                        {saveError && (
                          <div className="alert" role="alert">
                            <span>
                              {saveError}
                              {conflict && (
                                <small>{t("file_conflict_explanation")}</small>
                              )}
                            </span>
                            {conflict && (
                              <button
                                className="secondary"
                                disabled={saving || historyBusy}
                                onClick={refreshFiles}
                              >
                                {t("reload_file")}
                              </button>
                            )}
                          </div>
                        )}
                        {sessionExpired && (
                          <div className="alert" role="alert">
                            <span>{t("session_expired_draft_preserved")}</span>
                            <button
                              className="secondary"
                              disabled={reconnecting}
                              onClick={reconnect}
                            >
                              {reconnecting
                                ? t("reconnecting")
                                : t("reconnect")}
                            </button>
                          </div>
                        )}
                        {reconnected && (
                          <p className="save-status" role="status">
                            {t("session_restored_save_again")}
                          </p>
                        )}
                        {saved && (
                          <p className="save-status" role="status">
                            {t("file_saved")}
                            {document.backup && (
                              <span>
                                {t("backup_created")}: {document.backup}
                              </span>
                            )}
                          </p>
                        )}
                        {document.warning && (
                          <p className="alert" role="status">
                            {warningText(document.warning)}
                          </p>
                        )}
                        <div className="document-toolbar">
                          <button
                            className="secondary"
                            aria-pressed={display === "preview"}
                            onClick={() => setDisplay("preview")}
                          >
                            {t("preview")}
                          </button>
                          <button
                            className="secondary"
                            aria-pressed={display === "source"}
                            onClick={() => setDisplay("source")}
                          >
                            {t("source")}
                          </button>
                          <button
                            className="secondary"
                            disabled={saving || historyBusy}
                            onClick={loadHistory}
                          >
                            {t("history")}
                          </button>
                          {editing && (
                            <button
                              className="secondary"
                              aria-pressed={showChanges}
                              onClick={() => setShowChanges(!showChanges)}
                            >
                              {t("changes")}
                            </button>
                          )}
                        </div>
                        {history && (
                          <div className="backup-list">
                            <h3>{t("history")}</h3>
                            {!history.length && <p>{t("no_backups")}</p>}
                            {history.map((item) => (
                              <div key={item.id}>
                                <time>
                                  {new Date(
                                    item.modified * 1000,
                                  ).toLocaleString(
                                    window.document.documentElement.lang,
                                  )}
                                </time>
                                <button
                                  className="secondary"
                                  disabled={
                                    saving || historyBusy || !document.editable
                                  }
                                  onClick={() => loadBackup(item.id)}
                                >
                                  {t("load_backup")}
                                </button>
                              </div>
                            ))}
                          </div>
                        )}
                        {backupNotice && (
                          <p role="status">{t("backup_draft")}</p>
                        )}
                        {editing && showChanges && (
                          <pre
                            className="change-preview"
                            aria-label={t("changes")}
                          >
                            {diffLines(document.content, draft, {
                              timeout: 150,
                            })?.map((part, i) => (
                              <span
                                key={i}
                                className={
                                  part.added
                                    ? "diff-added"
                                    : part.removed
                                      ? "diff-removed"
                                      : ""
                                }
                              >
                                {part.value.split(/(?<=\n)/).map((line, n) => (
                                  <span key={n}>
                                    {part.added
                                      ? "+ "
                                      : part.removed
                                        ? "− "
                                        : "  "}
                                    {line}
                                  </span>
                                ))}
                              </span>
                            )) || (
                              <span>
                                {t("before")}
                                {document.content}
                                {t("after")}
                                {draft}
                              </span>
                            )}
                          </pre>
                        )}
                        {editing ? (
                          <>
                            <div className="editor-actions sticky-actions">
                              <span className="field-note">
                                {draft !== document.content
                                  ? t("unsaved_changes")
                                  : t("no_unsaved_changes")}
                              </span>
                              <button
                                className="secondary"
                                disabled={saving || historyBusy}
                                onClick={() => {
                                  if (mayDiscard()) resetEditor();
                                }}
                              >
                                {t("cancel_editing")}
                              </button>
                              <button
                                className="primary"
                                disabled={
                                  saving ||
                                  conflict ||
                                  sessionExpired ||
                                  draft === document.content
                                }
                                onClick={save}
                              >
                                {saving ? t("saving_file") : t("save_file")}
                              </button>
                            </div>
                            <label
                              className="editor-label"
                              htmlFor="file-editor"
                            >
                              {t("file_contents")}
                            </label>
                            <textarea
                              id="file-editor"
                              className="file-editor"
                              value={draft}
                              disabled={saving || historyBusy}
                              spellCheck={false}
                              onKeyDown={(event) => {
                                if (
                                  (event.ctrlKey || event.metaKey) &&
                                  event.key === "Enter"
                                ) {
                                  event.preventDefault();
                                  void save();
                                }
                              }}
                              onChange={(event) => {
                                setDraft(event.target.value);
                                report(event.target.value !== document.content);
                                setSaved(false);
                              }}
                            />
                            <p className="field-note">{t("editor_help")}</p>
                            {display === "preview" &&
                              /\.md$/i.test(path) &&
                              renderMarkdown(draft)}
                          </>
                        ) : (
                          <>
                            <div className="editor-actions">
                              {contentEditable &&
                                document.editable &&
                                typeof document.revision === "string" &&
                                !document.truncated && (
                                  <button
                                    className="secondary"
                                    onClick={() => {
                                      setDraft(document.content);
                                      setEditing(true);
                                      setSaveError("");
                                      setConflict(false);
                                      setSaved(false);
                                      report(false);
                                    }}
                                  >
                                    {t("edit_file")}
                                  </button>
                                )}
                              {(!document.editable || document.truncated) && (
                                <span className="field-note">
                                  {t("file_not_editable")}
                                </span>
                              )}
                            </div>
                            {display === "preview" && /\.md$/i.test(path)
                              ? renderMarkdown(document.content)
                              : renderSource(
                                  document.content || t("empty_document"),
                                )}
                          </>
                        )}
                      </>
                    )}
                  </>
                )}
              </div>
            </div>
            <details className="content-exclusions">
              <summary>{t("content_exclusions")}</summary>
              <p>{t("content_exclusions_description")}</p>
              {index.excluded.length > 0 && (
                <ul>
                  {index.excluded.map((reason, position) => (
                    <li key={position}>{exclusionText(reason)}</li>
                  ))}
                </ul>
              )}
            </details>
          </>
        )
      )}
    </section>
  );
}
