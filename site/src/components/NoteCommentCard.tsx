import { useEffect, useRef, useState } from "react";
import {
  CommentApiError,
  deleteComment,
  isAbortLike,
  type CommentItem,
  type ViewerSession,
} from "../data/comments";
import type { ViewerLoadStatus } from "./NoteCommentComposer";

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

export function canViewerDeleteComment(
  item: CommentItem,
  viewerStatus: ViewerLoadStatus,
  viewer: ViewerSession | null,
): boolean {
  if (viewerStatus !== "ready" || !viewer || !viewer.user || !viewer.csrfToken) {
    return false;
  }
  if (viewer.user.isCommentAdmin) {
    return true;
  }
  return item.author.kind === "member" && item.author.id === viewer.user.id;
}

interface NoteCommentCardProps {
  item: CommentItem;
  viewerStatus: ViewerLoadStatus;
  viewer: ViewerSession | null;
  onRefreshViewerAfterConflict: () => Promise<ViewerSession | null>;
  onCommentDeleted: (commentId: number) => void;
}

export function NoteCommentCard({
  item,
  viewerStatus,
  viewer,
  onRefreshViewerAfterConflict,
  onCommentDeleted,
}: NoteCommentCardProps) {
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const deleteCtrlRef = useRef<AbortController | null>(null);

  const canDelete = canViewerDeleteComment(item, viewerStatus, viewer);

  useEffect(() => {
    if (!canDelete && !deleting) {
      setConfirming(false);
    }
  }, [canDelete, deleting]);

  useEffect(() => {
    return () => {
      deleteCtrlRef.current?.abort();
      deleteCtrlRef.current = null;
    };
  }, []);

  const handleConfirmDelete = async () => {
    if (deleting || !viewer?.csrfToken) return;

    const ctrl = new AbortController();
    deleteCtrlRef.current?.abort();
    deleteCtrlRef.current = ctrl;
    setDeleting(true);
    setDeleteError(null);

    try {
      await deleteComment(item.id, viewer.csrfToken, ctrl.signal);
      if (ctrl.signal.aborted) return;
      onCommentDeleted(item.id);
    } catch (error: unknown) {
      if (isAbortLike(error, ctrl.signal)) return;

      if (error instanceof CommentApiError) {
        if (error.status === 404 || error.code === "comment_not_found") {
          onCommentDeleted(item.id);
          return;
        }

        if (error.code === "csrf_failed") {
          const refreshed = await onRefreshViewerAfterConflict();
          if (ctrl.signal.aborted) return;
          if (!refreshed) {
            setDeleteError("会话状态同步受阻，请点击上方「重试连接」后再试。");
            return;
          }
          if (canViewerDeleteComment(item, "ready", refreshed)) {
            setConfirming(true);
            setDeleteError("安全令牌已更新，请再次点击「确认删除」。");
          } else {
            setConfirming(false);
            setDeleteError("当前登录状态已变化，无法删除该条评论。");
          }
          return;
        }

        if (error.status === 401) {
          await onRefreshViewerAfterConflict();
          if (ctrl.signal.aborted) return;
          setConfirming(false);
          setDeleteError(error.message);
          return;
        }

        setConfirming(false);
        setDeleteError(error.message);
      } else {
        setDeleteError("评论删除未成功，请稍后重试。");
      }
    } finally {
      if (deleteCtrlRef.current === ctrl) {
        deleteCtrlRef.current = null;
        setDeleting(false);
      }
    }
  };

  return (
    <li className="note-comment-card">
      <div className="note-comment-meta">
        <span className="note-comment-author" data-author-kind={item.author.kind}>
          {item.author.displayName}
        </span>
        {item.author.kind === "guest" ? (
          <span className="note-comment-badge">访客</span>
        ) : null}
        <time className="note-comment-time" dateTime={item.createdAt}>
          {formatCommentTime(item.createdAt)}
        </time>

        {canDelete ? (
          confirming ? (
            <span className="note-comment-delete-confirm">
              <span className="note-comment-delete-prompt">确认删除？</span>
              <button
                type="button"
                className="note-comment-danger-btn"
                onClick={handleConfirmDelete}
                disabled={deleting}
              >
                {deleting ? "正在删除…" : "确认删除"}
              </button>
              <button
                type="button"
                className="note-comment-cancel-btn"
                onClick={() => {
                  setConfirming(false);
                  setDeleteError(null);
                }}
                disabled={deleting}
              >
                取消
              </button>
            </span>
          ) : (
            <button
              type="button"
              className="note-comment-delete-trigger"
              onClick={() => {
                setConfirming(true);
                setDeleteError(null);
              }}
            >
              删除
            </button>
          )
        ) : null}
      </div>

      <p className="note-comment-body">{item.body}</p>

      {deleteError ? (
        <p className="note-comment-delete-error" role="alert">
          {deleteError}
        </p>
      ) : null}
    </li>
  );
}
