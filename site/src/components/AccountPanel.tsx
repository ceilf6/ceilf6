import {
  useEffect,
  useRef,
  useState,
  type FocusEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { useLocation } from "react-router";
import type { SessionUser } from "../data/comments";

const HOVER_CLOSE_DELAY_MS = 150;
const COMBINING_MARK_RE = /^[\p{Mn}\p{Me}]$/u;

function isRegionalIndicator(char: string): boolean {
  const cp = char.codePointAt(0);
  return cp !== undefined && cp >= 0x1f1e6 && cp <= 0x1f1ff;
}

function isGraphemeExtender(char: string): boolean {
  const cp = char.codePointAt(0);
  if (cp === undefined) return false;
  if (cp === 0xfe0e || cp === 0xfe0f) return true;
  if (cp >= 0x1f3fb && cp <= 0x1f3ff) return true;
  return COMBINING_MARK_RE.test(char);
}

/**
 * 提取用户昵称的首个字素簇并转为大写，支持中文、组合音标、肤色修饰、国旗及 ZWJ 家庭 Emoji。
 */
export function extractAvatarInitial(name: string): string {
  const trimmed = name.trim();
  if (!trimmed) return "?";

  if (typeof Intl !== "undefined" && typeof Intl.Segmenter === "function") {
    const segmenter = new Intl.Segmenter("zh", { granularity: "grapheme" });
    const first = segmenter.segment(trimmed)[Symbol.iterator]().next();
    if (first.done || !first.value.segment) return "?";
    return first.value.segment.toUpperCase();
  }

  const chars = Array.from(trimmed);
  if (chars.length === 0) return "?";

  let cluster = chars[0];
  let i = 1;

  if (
    isRegionalIndicator(chars[0]) &&
    i < chars.length &&
    isRegionalIndicator(chars[i])
  ) {
    cluster += chars[i];
    i += 1;
  }

  while (i < chars.length) {
    const ch = chars[i];
    if (ch === "\u200D") {
      cluster += ch;
      i += 1;
      if (i < chars.length) {
        cluster += chars[i];
        i += 1;
      }
      continue;
    }
    if (isGraphemeExtender(ch)) {
      cluster += ch;
      i += 1;
      continue;
    }
    break;
  }

  return cluster.toUpperCase();
}

function supportsFineHover(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(hover: hover) and (pointer: fine)").matches
  );
}

type PanelMode = "closed" | "hover" | "pinned";

export interface AccountPanelProps {
  user: SessionUser;
  csrfToken: string;
  nextTarget?: string;
}

export function AccountPanel({
  user,
  csrfToken,
  nextTarget,
}: AccountPanelProps) {
  const location = useLocation();
  const effectiveNext = nextTarget ?? `${location.pathname}${location.search}`;

  const [mode, setMode] = useState<PanelMode>("closed");
  const open = mode !== "closed";

  const containerRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const closeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pointerDownInsideRef = useRef(false);

  const clearCloseTimer = () => {
    if (closeTimerRef.current !== null) {
      clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
  };

  useEffect(() => {
    return () => {
      if (closeTimerRef.current !== null) {
        clearTimeout(closeTimerRef.current);
        closeTimerRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (closeTimerRef.current !== null) {
      clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
    setMode("closed");
  }, [location.pathname, location.search, location.hash, location.key]);

  useEffect(() => {
    if (!open) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        const root = containerRef.current;
        const focusInside = Boolean(
          root && root.contains(document.activeElement),
        );
        const shouldRestoreFocus = mode === "pinned" || focusInside;
        clearCloseTimer();
        setMode("closed");
        if (shouldRestoreFocus) {
          triggerRef.current?.focus();
        }
      }
    };

    const handleOutsideDown = (event: PointerEvent) => {
      const root = containerRef.current;
      if (!root) return;
      if (event.target instanceof Node && !root.contains(event.target)) {
        clearCloseTimer();
        setMode("closed");
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    document.addEventListener("pointerdown", handleOutsideDown);

    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.removeEventListener("pointerdown", handleOutsideDown);
    };
  }, [open, mode]);

  const handlePointerEnter = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.pointerType === "touch") return;
    if (!supportsFineHover()) return;
    clearCloseTimer();
    setMode((prev) => (prev === "closed" ? "hover" : prev));
  };

  const handlePointerLeave = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.pointerType === "touch") return;
    if (!supportsFineHover()) return;
    clearCloseTimer();
    closeTimerRef.current = setTimeout(() => {
      closeTimerRef.current = null;
      if (
        containerRef.current?.contains(document.activeElement) &&
        panelRef.current?.contains(document.activeElement)
      ) {
        return;
      }
      setMode((prev) => (prev === "hover" ? "closed" : prev));
    }, HOVER_CLOSE_DELAY_MS);
  };

  const handleTriggerClick = () => {
    clearCloseTimer();
    setMode((prev) => (prev === "pinned" ? "closed" : "pinned"));
  };

  const markPointerDownInside = () => {
    pointerDownInsideRef.current = true;
    setTimeout(() => {
      pointerDownInsideRef.current = false;
    }, 0);
  };

  const handleContainerBlur = (event: FocusEvent<HTMLDivElement>) => {
    const root = containerRef.current;
    if (!root || !open) return;

    const nextFocused = event.relatedTarget;
    if (nextFocused instanceof Node) {
      if (!root.contains(nextFocused)) {
        clearCloseTimer();
        setMode("closed");
      }
      return;
    }

    if (pointerDownInsideRef.current) {
      return;
    }

    queueMicrotask(() => {
      const currentRoot = containerRef.current;
      if (!currentRoot) return;
      if (!currentRoot.contains(document.activeElement)) {
        clearCloseTimer();
        setMode("closed");
      }
    });
  };

  const initial = extractAvatarInitial(user.displayName);
  const roleLabel = user.isCommentAdmin ? "站主" : "用户";
  const logoutAction = `/accounts/logout/?next=${encodeURIComponent(effectiveNext)}`;

  return (
    <div
      ref={containerRef}
      className="account-disclosure"
      onPointerEnter={handlePointerEnter}
      onPointerLeave={handlePointerLeave}
      onPointerDownCapture={markPointerDownInside}
      onBlur={handleContainerBlur}
    >
      <button
        ref={triggerRef}
        type="button"
        className="account-trigger"
        aria-expanded={open}
        aria-controls="account-panel"
        aria-label={`账号：${user.displayName}`}
        onClick={handleTriggerClick}
      >
        <span className="account-avatar-initial" aria-hidden="true">
          {initial}
        </span>
      </button>

      <div
        ref={panelRef}
        id="account-panel"
        className="account-panel account-panel-frosted"
        hidden={!open}
      >
        <div className="account-panel-header">
          <span className="account-panel-name">{user.displayName}</span>
          <span className="account-panel-sep" aria-hidden="true">
            {" · "}
          </span>
          <span className="account-panel-role">{roleLabel}</span>
        </div>

        <form
          className="account-logout-form"
          method="post"
          action={logoutAction}
        >
          <input type="hidden" name="csrfmiddlewaretoken" value={csrfToken} />
          <input type="hidden" name="next" value={effectiveNext} />
          <button type="submit" className="account-logout-btn">
            退出登录
          </button>
        </form>
      </div>
    </div>
  );
}
