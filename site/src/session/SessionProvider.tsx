import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  fetchViewerSession,
  isAbortLike,
  type ViewerSession,
} from "../data/comments";

export type SessionStatus = "idle" | "loading" | "ready" | "error";

export interface SessionContextValue {
  status: SessionStatus;
  session: ViewerSession | null;
  refresh: () => Promise<ViewerSession | null>;
  syncSession: (session: ViewerSession) => void;
}

const VISIBILITY_REFRESH_THROTTLE_MS = 10_000;

const noopRefresh = (): Promise<ViewerSession | null> => Promise.resolve(null);
const noopSync = (_session: ViewerSession): void => {};

const DEFAULT_SESSION_CONTEXT: SessionContextValue = {
  status: "idle",
  session: null,
  refresh: noopRefresh,
  syncSession: noopSync,
};

const SessionContext = createContext<SessionContextValue>(
  DEFAULT_SESSION_CONTEXT,
);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<SessionStatus>("loading");
  const [session, setSession] = useState<ViewerSession | null>(null);

  const requestSeqRef = useRef(0);
  const activeCtrlRef = useRef<AbortController | null>(null);
  const lastFetchedAtRef = useRef<number>(0);
  const hasReadySessionRef = useRef(false);

  const refresh = useCallback(async (): Promise<ViewerSession | null> => {
    const seq = requestSeqRef.current + 1;
    requestSeqRef.current = seq;

    activeCtrlRef.current?.abort();
    const ctrl = new AbortController();
    activeCtrlRef.current = ctrl;

    try {
      const next = await fetchViewerSession(ctrl.signal);
      if (seq !== requestSeqRef.current || ctrl.signal.aborted) {
        return null;
      }
      hasReadySessionRef.current = true;
      lastFetchedAtRef.current = Date.now();
      setSession(next);
      setStatus("ready");
      return next;
    } catch (error: unknown) {
      if (seq !== requestSeqRef.current || isAbortLike(error, ctrl.signal)) {
        return null;
      }
      if (!hasReadySessionRef.current) {
        setSession(null);
        setStatus("error");
      }
      return null;
    } finally {
      if (activeCtrlRef.current === ctrl) {
        activeCtrlRef.current = null;
      }
    }
  }, []);

  const syncSession = useCallback((nextSession: ViewerSession): void => {
    requestSeqRef.current += 1;
    activeCtrlRef.current?.abort();
    activeCtrlRef.current = null;
    hasReadySessionRef.current = true;
    lastFetchedAtRef.current = Date.now();
    setSession(nextSession);
    setStatus("ready");
  }, []);

  useEffect(() => {
    void refresh();
    return () => {
      requestSeqRef.current += 1;
      activeCtrlRef.current?.abort();
      activeCtrlRef.current = null;
    };
  }, [refresh]);

  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState !== "visible") return;
      if (Date.now() - lastFetchedAtRef.current > VISIBILITY_REFRESH_THROTTLE_MS) {
        void refresh();
      }
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [refresh]);

  const value = useMemo<SessionContextValue>(
    () => ({
      status,
      session,
      refresh,
      syncSession,
    }),
    [status, session, refresh, syncSession],
  );

  return (
    <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
  );
}

export function useSession(): SessionContextValue {
  return useContext(SessionContext);
}
