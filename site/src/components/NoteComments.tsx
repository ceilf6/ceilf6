import { useCallback, useEffect, useRef, useState } from "react";
import {
  fetchNoteComments,
  fetchViewerSession,
  isAbortLike,
  type CommentItem,
  type ViewerSession,
} from "../data/comments";
import { NoteCommentComposer, type ViewerLoadStatus } from "./NoteCommentComposer";
import "./NoteComments.css";

interface NoteCommentsProps {
  slug: string;
}

type ListStatus = "loading" | "ready" | "error";

const SHANGHAI_TIME_FORMATTER = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

function formatCommentTime(iso: string): string {
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return iso;
  return SHANGHAI_TIME_FORMATTER.format(new Date(ms)).replace(/\//g, "-");
}

export function NoteComments({ slug }: NoteCommentsProps) {
  const [viewerStatus, setViewerStatus] = useState<ViewerLoadStatus>("loading");
  const [viewer, setViewer] = useState<ViewerSession | null>(null);
  const [viewerReloadSeq, setViewerReloadSeq] = useState(0);

  const [status, setStatus] = useState<ListStatus>("loading");
  const [items, setItems] = useState<CommentItem[]>([]);
  const [nextBefore, setNextBefore] = useState<number | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadMoreError, setLoadMoreError] = useState<string | null>(null);
  const [reloadSeq, setReloadSeq] = useState(0);

  const loadMoreCtrlRef = useRef<AbortController | null>(null);
  const conflictCtrlRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    setViewerStatus("loading");
    setViewer(null);

    fetchViewerSession(ctrl.signal)
      .then((session) => {
        if (ctrl.signal.aborted) return;
        setViewer(session);
        setViewerStatus("ready");
      })
      .catch((error: unknown) => {
        if (isAbortLike(error, ctrl.signal)) return;
        setViewerStatus("error");
      });

    return () => {
      ctrl.abort();
    };
  }, [slug, viewerReloadSeq]);

  useEffect(() => {
    const ctrl = new AbortController();
    loadMoreCtrlRef.current?.abort();
    loadMoreCtrlRef.current = null;
    conflictCtrlRef.current?.abort();
    conflictCtrlRef.current = null;

    setStatus("loading");
    setItems([]);
    setNextBefore(null);
    setLoadingMore(false);
    setLoadMoreError(null);

    fetchNoteComments(slug, { signal: ctrl.signal })
      .then((page) => {
        if (ctrl.signal.aborted) return;
        setItems(page.items);
        setNextBefore(page.nextBefore);
        setStatus("ready");
      })
      .catch((error: unknown) => {
        if (isAbortLike(error, ctrl.signal)) return;
        setStatus("error");
      });

    return () => {
      ctrl.abort();
      loadMoreCtrlRef.current?.abort();
      loadMoreCtrlRef.current = null;
      conflictCtrlRef.current?.abort();
      conflictCtrlRef.current = null;
    };
  }, [slug, reloadSeq]);

  const handleRefreshViewerAfterConflict = useCallback(async () => {
    const ctrl = new AbortController();
    conflictCtrlRef.current?.abort();
    conflictCtrlRef.current = ctrl;

    try {
      const [refreshed, refreshedPage] = await Promise.all([
        fetchViewerSession(ctrl.signal),
        fetchNoteComments(slug, { signal: ctrl.signal }).catch(() => null),
      ]);
      if (ctrl.signal.aborted) return null;
      setViewer(refreshed);
      setViewerStatus("ready");
      if (refreshedPage) {
        setItems(refreshedPage.items);
        setNextBefore(refreshedPage.nextBefore);
        setStatus("ready");
      }
      return refreshed;
    } catch (error: unknown) {
      if (!isAbortLike(error, ctrl.signal)) {
        setViewerStatus("error");
      }
      return null;
    } finally {
      if (conflictCtrlRef.current === ctrl) {
        conflictCtrlRef.current = null;
      }
    }
  }, [slug]);

  const handleDisableGuestComments = useCallback(() => {
    setViewer((prev) =>
      prev ? { ...prev, guestCommentsAllowed: false } : prev,
    );
  }, []);

  const handleCommentCreated = useCallback((created: CommentItem) => {
    setItems((prev) => [
      created,
      ...prev.filter((existing) => existing.id !== created.id),
    ]);
    setStatus("ready");
  }, []);

  const handleLoadMore = () => {
    if (nextBefore === null || loadingMore) return;

    const ctrl = new AbortController();
    loadMoreCtrlRef.current?.abort();
    loadMoreCtrlRef.current = ctrl;
    setLoadingMore(true);
    setLoadMoreError(null);

    fetchNoteComments(slug, { before: nextBefore, signal: ctrl.signal })
      .then((page) => {
        if (ctrl.signal.aborted) return;
        setItems((prev) => {
          const seen = new Set(prev.map((item) => item.id));
          const appended = page.items.filter((item) => !seen.has(item.id));
          return [...prev, ...appended];
        });
        setNextBefore(page.nextBefore);
        setLoadingMore(false);
      })
      .catch((error: unknown) => {
        if (isAbortLike(error, ctrl.signal)) return;
        setLoadMoreError("更多评论暂时无法读取，请重试。");
        setLoadingMore(false);
      })
      .finally(() => {
        if (loadMoreCtrlRef.current === ctrl) {
          loadMoreCtrlRef.current = null;
        }
      });
  };

  return (
    <section className="note-comments" aria-labelledby="note-comments-heading">
      <div className="note-comments-head">
        <h2 id="note-comments-heading" className="note-comments-title">
          评论
        </h2>
        {status === "ready" && items.length > 0 ? (
          <span className="note-comments-count">已展示 {items.length} 条</span>
        ) : null}
      </div>

      <NoteCommentComposer
        slug={slug}
        viewerStatus={viewerStatus}
        viewer={viewer}
        onRetryViewer={() => setViewerReloadSeq((n) => n + 1)}
        onRefreshViewerAfterConflict={handleRefreshViewerAfterConflict}
        onDisableGuestComments={handleDisableGuestComments}
        onCommentCreated={handleCommentCreated}
      />

      {status === "loading" ? (
        <p className="note-comments-state" role="status">
          正在读取评论…
        </p>
      ) : status === "error" ? (
        <div className="note-comments-state note-comments-state-error" role="alert">
          <p>评论暂时无法读取，请稍后重试。</p>
          <button
            type="button"
            className="note-comments-btn"
            onClick={() => setReloadSeq((n) => n + 1)}
          >
            重新读取
          </button>
        </div>
      ) : items.length === 0 ? (
        <p className="note-comments-empty">还没有评论，欢迎留下第一条讨论。</p>
      ) : (
        <>
          <ol className="note-comments-list">
            {items.map((item) => (
              <li key={item.id} className="note-comment-card">
                <div className="note-comment-meta">
                  <span
                    className="note-comment-author"
                    data-author-kind={item.author.kind}
                  >
                    {item.author.displayName}
                  </span>
                  {item.author.kind === "guest" ? (
                    <span className="note-comment-badge">访客</span>
                  ) : null}
                  <time className="note-comment-time" dateTime={item.createdAt}>
                    {formatCommentTime(item.createdAt)}
                  </time>
                </div>
                <p className="note-comment-body">{item.body}</p>
              </li>
            ))}
          </ol>

          {loadMoreError ? (
            <p className="note-comments-more-error" role="alert">
              {loadMoreError}
            </p>
          ) : null}

          {nextBefore !== null ? (
            <div className="note-comments-more">
              <button
                type="button"
                className="note-comments-btn"
                onClick={handleLoadMore}
                disabled={loadingMore}
              >
                {loadingMore ? "正在读取更多…" : "读取更多评论"}
              </button>
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}
