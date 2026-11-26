import { extractAvatarInitial, isValidAvatarColor } from "../data/avatar";
import type { CommentAuthor } from "../data/comments";
import "./CommentAvatar.css";

export interface CommentAvatarProps {
  author: CommentAuthor;
}

export function CommentAvatar({ author }: CommentAvatarProps) {
  if (author.kind === "guest") {
    return (
      <span className="comment-avatar is-guest" aria-hidden="true">
        <svg
          width="15"
          height="15"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <circle cx="12" cy="8" r="4" />
          <path d="M5 20a7 7 0 0 1 14 0" />
        </svg>
      </span>
    );
  }

  const validColor = isValidAvatarColor(author.avatarColor)
    ? author.avatarColor
    : undefined;
  const hasCustomColor = validColor !== undefined;

  return (
    <span
      className={`comment-avatar is-member${hasCustomColor ? " has-custom-color" : ""}`}
      style={hasCustomColor ? { backgroundColor: validColor } : undefined}
      aria-hidden="true"
    >
      {extractAvatarInitial(author.displayName)}
    </span>
  );
}
