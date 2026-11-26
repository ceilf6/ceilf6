import { isValidAvatarColor } from "./avatar";

export { isValidAvatarColor };

export const MAX_COMMENT_BODY_LENGTH = 1000;

const DRAFT_STORAGE_PREFIX = "wangjinghong:note-comment-draft:";

export interface SessionUser {
  id: number;
  displayName: string;
  isCommentAdmin: boolean;
  avatarColor?: string;
}

export interface ViewerSession {
  user: SessionUser | null;
  csrfToken: string;
  guestCommentsAllowed: boolean;
}

export type CommentAuthorKind = "guest" | "member";

export interface CommentAuthor {
  kind: CommentAuthorKind;
  id: number | null;
  displayName: string;
  avatarColor?: string;
}

export interface CommentItem {
  id: number;
  body: string;
  createdAt: string;
  canDelete: boolean;
  author: CommentAuthor;
}

export interface CommentListPage {
  items: CommentItem[];
  nextBefore: number | null;
}

export interface CreateNoteCommentInput {
  body: string;
  expectedAuthorKind: CommentAuthorKind;
  website?: string;
}

export interface CommentApiErrorOptions {
  actualAuthorKind?: CommentAuthorKind;
  retryAfterSeconds?: number;
}

export class CommentApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly actualAuthorKind?: CommentAuthorKind;
  readonly retryAfterSeconds?: number;

  constructor(
    message: string,
    status: number,
    code = "unknown_error",
    options: CommentApiErrorOptions = {},
  ) {
    super(message);
    this.name = "CommentApiError";
    this.status = status;
    this.code = code;
    this.actualAuthorKind = options.actualAuthorKind;
    this.retryAfterSeconds = options.retryAfterSeconds;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isPositiveSafeInt(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 1;
}

export function isAbortLike(error: unknown, signal?: AbortSignal): boolean {
  if (signal?.aborted) return true;
  return error instanceof DOMException && error.name === "AbortError";
}

function assertValidNoteSlug(slug: string): void {
  if (!slug || slug === "." || slug === ".." || slug.includes("/")) {
    throw new CommentApiError("未找到对应的札记。", 400, "invalid_note_slug");
  }
}

function parseRetryAfterHeader(response: Response): number | undefined {
  const raw = response.headers?.get?.("Retry-After")?.trim();
  if (!raw || !/^\d+$/.test(raw)) return undefined;
  const parsed = Number(raw);
  return Number.isSafeInteger(parsed) && parsed >= 1 ? parsed : undefined;
}

async function readJsonOrThrow(
  response: Response,
  signal?: AbortSignal,
): Promise<Record<string, unknown>> {
  let parsed: unknown = null;
  try {
    parsed = await response.json();
  } catch (error: unknown) {
    if (isAbortLike(error, signal)) {
      throw error;
    }
    throw new CommentApiError(
      "服务响应格式异常，请稍后重试。",
      response.status,
      "invalid_response_json",
    );
  }

  if (!response.ok) {
    const code =
      isRecord(parsed) && typeof parsed.code === "string"
        ? parsed.code
        : `http_${response.status}`;
    const message =
      isRecord(parsed) && typeof parsed.message === "string" && parsed.message.trim()
        ? parsed.message
        : "评论服务暂时不可用，请稍后重试。";
    const actualAuthorKind =
      isRecord(parsed) &&
      (parsed.actualAuthorKind === "guest" || parsed.actualAuthorKind === "member")
        ? parsed.actualAuthorKind
        : undefined;
    const retryAfterSeconds =
      response.status === 429 ? parseRetryAfterHeader(response) : undefined;
    throw new CommentApiError(message, response.status, code, {
      actualAuthorKind,
      retryAfterSeconds,
    });
  }

  if (!isRecord(parsed)) {
    throw new CommentApiError(
      "服务返回结构异常，请稍后重试。",
      response.status,
      "invalid_response_shape",
    );
  }
  return parsed;
}

export function parseCommentItem(raw: unknown): CommentItem {
  if (!isRecord(raw) || !isRecord(raw.author)) {
    throw new CommentApiError("评论数据格式异常。", 500, "invalid_comment_item");
  }
  const { id, body, createdAt, canDelete, author } = raw;
  const kind = author.kind;
  const validAuthorId =
    kind === "guest"
      ? author.id === null
      : kind === "member" && isPositiveSafeInt(author.id);

  if (
    !isPositiveSafeInt(id) ||
    typeof body !== "string" ||
    typeof createdAt !== "string" ||
    typeof canDelete !== "boolean" ||
    (kind !== "guest" && kind !== "member") ||
    !validAuthorId ||
    typeof author.displayName !== "string"
  ) {
    throw new CommentApiError("评论字段格式异常。", 500, "invalid_comment_fields");
  }

  return {
    id,
    body,
    createdAt,
    canDelete,
    author: {
      kind,
      id: author.id as number | null,
      displayName: author.displayName,
      ...(kind === "member" && isValidAvatarColor(author.avatarColor)
        ? { avatarColor: author.avatarColor }
        : {}),
    },
  };
}

export async function fetchViewerSession(signal?: AbortSignal): Promise<ViewerSession> {
  const response = await fetch("/api/me/", {
    method: "GET",
    credentials: "same-origin",
    headers: { Accept: "application/json" },
    signal,
  });
  const data = await readJsonOrThrow(response, signal);

  let user: SessionUser | null = null;
  if (data.user !== null) {
    if (
      !isRecord(data.user) ||
      !isPositiveSafeInt(data.user.id) ||
      typeof data.user.displayName !== "string" ||
      typeof data.user.isCommentAdmin !== "boolean"
    ) {
      throw new CommentApiError("会话身份数据格式异常。", 500, "invalid_viewer_user");
    }
    user = {
      id: data.user.id,
      displayName: data.user.displayName,
      isCommentAdmin: data.user.isCommentAdmin,
      ...(isValidAvatarColor(data.user.avatarColor)
        ? { avatarColor: data.user.avatarColor }
        : {}),
    };
  }

  if (
    typeof data.csrfToken !== "string" ||
    typeof data.guestCommentsAllowed !== "boolean"
  ) {
    throw new CommentApiError("会话配置数据格式异常。", 500, "invalid_viewer_session");
  }

  return {
    user,
    csrfToken: data.csrfToken,
    guestCommentsAllowed: data.guestCommentsAllowed,
  };
}

export interface FetchNoteCommentsOptions {
  before?: number;
  signal?: AbortSignal;
}

export async function fetchNoteComments(
  slug: string,
  options: FetchNoteCommentsOptions = {},
): Promise<CommentListPage> {
  assertValidNoteSlug(slug);
  if (options.before !== undefined && !isPositiveSafeInt(options.before)) {
    throw new CommentApiError("分页游标参数无效。", 400, "invalid_cursor");
  }

  const encodedSlug = encodeURIComponent(slug);
  const query =
    options.before !== undefined
      ? `?before=${encodeURIComponent(String(options.before))}`
      : "";
  const response = await fetch(`/api/notes/${encodedSlug}/comments/${query}`, {
    method: "GET",
    credentials: "same-origin",
    headers: { Accept: "application/json" },
    signal: options.signal,
  });
  const data = await readJsonOrThrow(response, options.signal);

  if (
    !Array.isArray(data.items) ||
    (data.nextBefore !== null && !isPositiveSafeInt(data.nextBefore))
  ) {
    throw new CommentApiError("评论列表结构异常。", 500, "invalid_comment_page");
  }

  return {
    items: data.items.map(parseCommentItem),
    nextBefore: data.nextBefore,
  };
}

export async function createNoteComment(
  slug: string,
  input: CreateNoteCommentInput,
  csrfToken: string,
  signal?: AbortSignal,
): Promise<CommentItem> {
  assertValidNoteSlug(slug);
  const token = csrfToken.trim();
  if (!token) {
    throw new CommentApiError(
      "安全令牌尚未就绪，请刷新重试。",
      400,
      "missing_csrf_token",
    );
  }

  const encodedSlug = encodeURIComponent(slug);
  const response = await fetch(`/api/notes/${encodedSlug}/comments/`, {
    method: "POST",
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "X-CSRFToken": token,
    },
    body: JSON.stringify({
      body: input.body,
      expectedAuthorKind: input.expectedAuthorKind,
      website: input.website ?? "",
    }),
    signal,
  });
  const data = await readJsonOrThrow(response, signal);
  return parseCommentItem(data);
}

export async function deleteComment(
  commentId: number,
  csrfToken: string,
  signal?: AbortSignal,
): Promise<void> {
  if (!isPositiveSafeInt(commentId)) {
    throw new CommentApiError("未找到对应的评论。", 404, "comment_not_found");
  }
  const token = csrfToken.trim();
  if (!token) {
    throw new CommentApiError(
      "安全令牌尚未就绪，请刷新重试。",
      400,
      "missing_csrf_token",
    );
  }

  const encodedId = encodeURIComponent(String(commentId));
  const response = await fetch(`/api/comments/${encodedId}/delete/`, {
    method: "POST",
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
      "X-CSRFToken": token,
    },
    signal,
  });

  if (response.status === 204) {
    return;
  }
  if (!response.ok) {
    await readJsonOrThrow(response, signal);
  }
  throw new CommentApiError(
    "服务响应状态异常，请稍后重试。",
    response.status,
    "unexpected_delete_status",
  );
}

export function readCommentDraft(slug: string): string {
  if (!slug) return "";
  try {
    return globalThis.sessionStorage?.getItem(`${DRAFT_STORAGE_PREFIX}${slug}`) ?? "";
  } catch {
    return "";
  }
}

export function writeCommentDraft(slug: string, draft: string): void {
  if (!slug) return;
  const key = `${DRAFT_STORAGE_PREFIX}${slug}`;
  try {
    if (draft) {
      globalThis.sessionStorage?.setItem(key, draft);
    } else {
      globalThis.sessionStorage?.removeItem(key);
    }
  } catch {
    // sessionStorage 被隐私模式禁用或配额满时静默退化为内存态草稿
  }
}
