import { useEffect, useState, type MouseEvent } from "react";
import { Link, useLocation } from "react-router";
import { GITHUB_URL } from "../data/site";
import { useSession } from "../session/SessionProvider";
import { AccountPanel } from "./AccountPanel";
import "./SiteHeader.css";

interface NavItem {
  label: string;
  to: string;
  matches: (pathname: string) => boolean;
}

const NAV_ITEMS: readonly NavItem[] = [
  {
    label: "博客论坛",
    to: "/blog",
    matches: (pathname) => pathname === "/blog" || pathname.startsWith("/blog/"),
  },
  {
    label: "项目视频",
    to: "/vlog",
    matches: (pathname) => pathname === "/vlog" || pathname.startsWith("/vlog/"),
  },
  {
    label: "证书画廊",
    to: "/awards",
    matches: (pathname) =>
      pathname === "/awards" || pathname.startsWith("/awards/"),
  },
];

export function SiteHeader() {
  const location = useLocation();
  const { status, session } = useSession();
  const [scrolled, setScrolled] = useState(
    () => typeof window !== "undefined" && window.scrollY > 8,
  );

  useEffect(() => {
    const syncScrollState = () => {
      setScrolled(window.scrollY > 8);
    };
    syncScrollState();
    window.addEventListener("scroll", syncScrollState, { passive: true });
    return () => {
      window.removeEventListener("scroll", syncScrollState);
    };
  }, [location.pathname]);

  const isTransparent = location.pathname === "/" && !scrolled;
  const nextTarget = `${location.pathname}${location.search}`;
  const loginHref = `/accounts/login/?next=${encodeURIComponent(nextTarget)}`;

  const handleBrandClick = (event: MouseEvent<HTMLAnchorElement>) => {
    if (location.pathname !== "/") return;
    event.preventDefault();
    const prefersReducedMotion =
      typeof window !== "undefined" &&
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    window.scrollTo({
      top: 0,
      behavior: prefersReducedMotion ? "auto" : "smooth",
    });
  };

  return (
    <header
      className={`site-header ${isTransparent ? "is-transparent" : "is-frosted"}`}
    >
      <div className="site-header-inner">
        <Link
          to="/"
          className="site-header-brand"
          onClick={handleBrandClick}
        >
          王景宏
        </Link>

        <nav className="site-header-nav" aria-label="主导航">
          {NAV_ITEMS.map((item) => {
            const active = item.matches(location.pathname);
            return (
              <Link
                key={item.to}
                to={item.to}
                className={`site-header-nav-link${active ? " is-active" : ""}`}
                aria-current={active ? "page" : undefined}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div className="site-header-actions">
          <a
            href={GITHUB_URL}
            target="_blank"
            rel="noopener noreferrer"
            aria-label="GitHub 主页（新窗口打开）"
            className="site-header-github"
          >
            <svg
              viewBox="0 0 24 24"
              width="20"
              height="20"
              fill="currentColor"
              aria-hidden="true"
            >
              <path d="M12 .5C5.65.5.5 5.65.5 12a11.5 11.5 0 0 0 7.86 10.92c.58.1.79-.25.79-.56v-2.02c-3.2.7-3.88-1.38-3.88-1.38-.52-1.33-1.28-1.68-1.28-1.68-1.05-.72.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.7 1.26 3.36.96.1-.75.4-1.26.73-1.55-2.55-.29-5.24-1.28-5.24-5.69 0-1.26.45-2.29 1.19-3.1-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.18 1.18a11.05 11.05 0 0 1 5.8 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.59.23 2.76.11 3.05.74.81 1.19 1.84 1.19 3.1 0 4.42-2.7 5.39-5.27 5.68.42.36.78 1.06.78 2.14v3.17c0 .31.21.67.8.56A11.5 11.5 0 0 0 23.5 12C23.5 5.65 18.35.5 12 .5Z" />
            </svg>
          </a>

          {status === "loading" || status === "idle" ? (
            <span
              className="site-header-account-skeleton"
              aria-hidden="true"
            />
          ) : status === "error" || !session || !session.user ? (
            <a href={loginHref} className="site-header-login">
              登录
            </a>
          ) : (
            <AccountPanel
              user={session.user}
              csrfToken={session.csrfToken}
              nextTarget={nextTarget}
            />
          )}
        </div>
      </div>
    </header>
  );
}
