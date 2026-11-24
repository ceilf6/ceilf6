import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  CommentApiError,
  MAX_COMMENT_BODY_LENGTH,
  createNoteComment,
  isAbortLike,
  readCommentDraft,
  writeCommentDraft,
  type CommentItem,
  type ViewerSession,
} from "../data/comments";

export type ViewerLoadStatus = "loading" | "ready" | "error";

interface NoteCommentComposerProps {
  slug: string;
  viewerStatus: ViewerLoadStatus;
  viewer: ViewerSession | null;
  onRetryViewer: () => void;
  onRefreshViewerAfterConflict: () => Promise<ViewerSession | null>;
  onDisableGuestComments: () => void;
  onCommentCreated: (comment: CommentItem) => void;
}

function countNormalizedChars(raw: string): number {
  const normalized = raw.replace(/\r\n?/g, "\n").trim();
  return Array.from(normalized).length;
}

export function NoteCommentComposer({
  slug,
  viewerStatus,
  viewer,
  onRetryViewer,
  onRefreshViewerAfterConflict,
  onDisableGuestComments,
  onCommentCreated,
}: NoteCommentComposerProps) {
  const [draft, setDraft] = useState<string>(() => readCommentDraft(slug));
  const [website, setWebsite] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const submitCtrlRef = useRef<AbortController | null>(null);

  useEffect(() => {
    submitCtrlRef.current?.abort();
    submitCtrlRef.current = null;
    setDraft(readCommentDraft(slug));
    setWebsite("");
    setSubmitting(false);
    setSubmitError(null);

    return () => {
      submitCtrlRef.current?.abort();
      submitCtrlRef.current = null;
    };
  }, [slug]);

  const notePath = `/notes/${encodeURIComponent(slug)}`;
  const nextQuery = encodeURIComponent(notePath);
  const loginHref = `/accounts/login/?next=${nextQuery}`;
  const signupHref = `/accounts/signup/?next=${nextQuery}`;
  const logoutAction = `/accounts/logout/?next=${nextQuery}`;

  const charCount = countNormalizedChars(draft);
  const overLimit = charCount > MAX_COMMENT_BODY_LENGTH;
  const isGuestPaused =
    viewerStatus === "ready" &&
    viewer !== null &&
    viewer.user === null &&
    !viewer.guestCommentsAllowed;

  const canSubmit =
    viewerStatus === "ready" &&
    viewer !== null &&
    Boolean(viewer.csrfToken) &&
    !isGuestPaused &&
    !submitting &&
    charCount >= 1 &&
    !overLimit;

  const handleDraftChange = (nextDraft: string) => {
    setDraft(nextDraft);
    writeCommentDraft(slug, nextDraft);
    if (submitError) setSubmitError(null);
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canSubmit || !viewer) return;

    const ctrl = new AbortController();
    submitCtrlRef.current?.abort();
    submitCtrlRef.current = ctrl;
    setSubmitting(true);
    setSubmitError(null);

    const prevUserId = viewer.user?.id ?? null;
    const expectedAuthorKind = viewer.user ? "member" : "guest";
    try {
      const created = await createNoteComment(
        slug,
        { body: draft, expectedAuthorKind, website },
        viewer.csrfToken,
        ctrl.signal,
      );
      if (ctrl.signal.aborted) return;
      setDraft("");
      writeCommentDraft(slug, "");
      setWebsite("");
      onCommentCreated(created);
    } catch (error: unknown) {
      if (isAbortLike(error, ctrl.signal)) return;

      if (error instanceof CommentApiError) {
        if (
          error.code === "author_state_changed" ||
          error.code === "csrf_failed"
        ) {
          const refreshed = await onRefreshViewerAfterConflict();
          if (ctrl.signal.aborted) return;
          if (!refreshed) {
            setSubmitError(
              "发言身份同步受阻，草稿已保留，请点击「重试连接」后再试。",
            );
            return;
          }
          const nextUserId = refreshed.user?.id ?? null;
          const identityChanged =
            prevUserId !== nextUserId || error.code === "author_state_changed";

          if (!refreshed.user && !refreshed.guestCommentsAllowed) {
            setSubmitError(
              "登录会话已过期且当前已暂停访客评论；草稿已保留，请重新登录后发表。",
            );
          } else if (!identityChanged) {
            setSubmitError("安全令牌已更新，草稿已保留，请再次点击发表。");
          } else if (refreshed.user) {
            setSubmitError(
              `登录状态已更新为「${refreshed.user.displayName}」，草稿已保留，请确认身份后再次点击发表。`,
            );
          } else {
            setSubmitError(
              "登录状态已变化（当前为「未登录用户」），草稿已保留，请确认身份后再次点击发表。",
            );
          }
          return;
        }

        if (error.code === "guest_comments_disabled") {
          onDisableGuestComments();
        }

        const retryHint =
          error.status === 429 && error.retryAfterSeconds
            ? `（建议 ${error.retryAfterSeconds} 秒后重试）`
            : "";
        setSubmitError(`${error.message}${retryHint}`);
      } else {
        setSubmitError("评论提交未成功，草稿已保留，请稍后重试。");
      }
    } finally {
      if (submitCtrlRef.current === ctrl) {
        submitCtrlRef.current = null;
        setSubmitting(false);
      }
    }
  };

  return (
    <div className="note-comment-composer">
      <div className="note-comment-identity">
        {viewerStatus === "loading" ? (
          <span className="note-comment-identity-text">正在确认发言身份…</span>
        ) : viewerStatus === "error" || !viewer ? (
          <>
            <span className="note-comment-identity-text">
              发言身份暂时无法确认，草稿已在本地保留。
            </span>
            <button
              type="button"
              className="note-comment-link-btn"
              onClick={onRetryViewer}
            >
              重试连接
            </button>
          </>
        ) : viewer.user ? (
          <>
            <span className="note-comment-identity-text">
              当前以 <strong>{viewer.user.displayName}</strong> 身份发表
            </span>
            <form
              className="note-comment-logout-form"
              method="post"
              action={logoutAction}
            >
              <input
                type="hidden"
                name="csrfmiddlewaretoken"
                value={viewer.csrfToken}
              />
              <input type="hidden" name="next" value={notePath} />
              <button type="submit" className="note-comment-link-btn">
                退出登录
              </button>
            </form>
          </>
        ) : viewer.guestCommentsAllowed ? (
          <>
            <span className="note-comment-identity-text">
              当前未登录，将以「未登录用户」身份直接发表
            </span>
            <span className="note-comment-auth-links">
              <a href={loginHref}>登录</a>
              <span aria-hidden="true">·</span>
              <a href={signupHref}>注册</a>
            </span>
          </>
        ) : (
          <>
            <span className="note-comment-identity-text">
              当前已暂停未登录访客发表评论，请先登录后发言（草稿将自动保留）
            </span>
            <span className="note-comment-auth-links">
              <a href={loginHref}>登录</a>
              <span aria-hidden="true">·</span>
              <a href={signupHref}>注册</a>
            </span>
          </>
        )}
      </div>

      <form className="note-comment-form" onSubmit={handleSubmit} noValidate>
        <label className="note-comment-sr-only" htmlFor={`note-comment-body-${slug}`}>
          评论内容
        </label>
        <textarea
          id={`note-comment-body-${slug}`}
          className="note-comment-textarea"
          rows={4}
          placeholder={
            isGuestPaused
              ? "请先登录后发表评论（可在此先行记录草稿）…"
              : "写下你对这篇札记的想法…"
          }
          value={draft}
          onChange={(event) => handleDraftChange(event.target.value)}
          disabled={submitting}
        />

        <div className="note-comment-hp" aria-hidden="true">
          <label htmlFor={`note-comment-website-${slug}`}>Website</label>
          <input
            id={`note-comment-website-${slug}`}
            name="website"
            type="text"
            tabIndex={-1}
            autoComplete="off"
            value={website}
            onChange={(event) => setWebsite(event.target.value)}
          />
        </div>

        {submitError ? (
          <p className="note-comment-submit-error" role="alert">
            {submitError}
          </p>
        ) : null}

        <div className="note-comment-form-foot">
          <span
            className="note-comment-counter"
            data-over-limit={overLimit ? "true" : undefined}
          >
            {charCount} / {MAX_COMMENT_BODY_LENGTH}
          </span>
          <button
            type="submit"
            className="note-comments-btn note-comment-submit-btn"
            disabled={!canSubmit}
          >
            {submitting ? "正在发表…" : "发表评论"}
          </button>
        </div>
      </form>
    </div>
  );
}
