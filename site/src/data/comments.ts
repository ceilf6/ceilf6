export interface SessionUser {
  id: number;
  displayName: string;
  isCommentAdmin: boolean;
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

export class CommentApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(message: string, status: number, code = "unknown_error") {
    super(message);
    this.name = "CommentApiError";
    this.status = status;
    this.code = code;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

async function readJsonOrThrow(response: Response): Promise<Record<string, unknown>> {
  let parsed: unknown = null;
  try {
    parsed = await response.json();
  } catch {
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
    throw new CommentApiError(message, response.status, code);
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
  if (
    typeof id !== "number" ||
    !Number.isInteger(id) ||
    typeof body !== "string" ||
    typeof createdAt !== "string" ||
    typeof canDelete !== "boolean" ||
    (kind !== "guest" && kind !== "member") ||
    (author.id !== null && (typeof author.id !== "number" || !Number.isInteger(author.id))) ||
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
      id: author.id,
      displayName: author.displayName,
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
  const data = await readJsonOrThrow(response);

  let user: SessionUser | null = null;
  if (data.user !== null) {
    if (
      !isRecord(data.user) ||
      typeof data.user.id !== "number" ||
      typeof data.user.displayName !== "string" ||
      typeof data.user.isCommentAdmin !== "boolean"
    ) {
      throw new CommentApiError("会话身份数据格式异常。", 500, "invalid_viewer_user");
    }
    user = {
      id: data.user.id,
      displayName: data.user.displayName,
      isCommentAdmin: data.user.isCommentAdmin,
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
  const data = await readJsonOrThrow(response);

  if (
    !Array.isArray(data.items) ||
    (data.nextBefore !== null &&
      (typeof data.nextBefore !== "number" || !Number.isInteger(data.nextBefore)))
  ) {
    throw new CommentApiError("评论列表结构异常。", 500, "invalid_comment_page");
  }

  return {
    items: data.items.map(parseCommentItem),
    nextBefore: data.nextBefore,
  };
}
