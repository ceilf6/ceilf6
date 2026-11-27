import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type MouseEvent } from "react";
import { createPortal } from "react-dom";
import { Link, Navigate, useParams } from "react-router";
import { loadNoteHtml, notes } from "../data/notes";
import { NoteComments } from "../components/NoteComments";
import { PageTransition } from "../components/PageTransition";
import "./Note.css";

/** 正文三态绑定当前 slug：切换札记的首帧即同步视为 loading，避免旧文闪烁与评论接口提前误发；
    原子部署后旧 index.html 拉新 hash chunk 404 时落错误态，不永久停留「加载中」 */
type NoteBody =
  | "loading"
  | { slug: string; status: "error" }
  | { slug: string; status: "ready"; html: string };

export default function Note() {
  const { slug = "" } = useParams();
  const meta = notes.find((n) => n.slug === slug);
  const [body, setBody] = useState<NoteBody>("loading");
  /** 正文配图全屏查看:并排小图与长截图在手机上可点开看清;slug 切换即收起。
      full:原尺寸模式,宽表格类截图在手机上可横向平移看清小字 */
  const [zoom, setZoom] = useState<{ src: string; alt: string; full: boolean } | null>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLElement | null>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  const title = meta?.title;
  useEffect(() => {
    if (title) document.title = `王景宏 · 博客论坛 · ${title}`;
  }, [title]);

  useEffect(() => {
    let alive = true;
    setBody("loading"); // slug 切换即重置,不依赖 App 层 key 重挂载
    setZoom(null);
    const p = loadNoteHtml(slug);
    if (p) {
      p.then(
        (h) => alive && setBody({ slug, status: "ready", html: h }),
        () => alive && setBody({ slug, status: "error" }),
      );
    }
    return () => {
      alive = false;
    };
  }, [slug]);

  const closeZoom = () => setZoom(null);
  const closeZoomRef = useRef(closeZoom);
  closeZoomRef.current = closeZoom;

  const zoomOpen = zoom !== null;
  useEffect(() => {
    if (!zoomOpen) return;
    // 背景整体 inert:点击图片后焦点即使落到 body,Tab 也只能在弹层内移动
    const background = [...document.body.children].filter(
      (el) => !el.contains(dialogRef.current) && !el.hasAttribute("inert"),
    );
    background.forEach((el) => el.setAttribute("inert", ""));
    closeRef.current?.focus();
    const onKey = (e: globalThis.KeyboardEvent) => e.key === "Escape" && closeZoomRef.current();
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      background.forEach((el) => el.removeAttribute("inert"));
      // 解除 inert 后背景才可聚焦,回焦放在这里;切文章时原图已卸载则跳过
      const trigger = triggerRef.current;
      if (trigger?.isConnected) trigger.focus();
    };
  }, [zoomOpen]);

  // 正文是构建期 HTML 串,img 不是 React 节点:事件委托 + 挂载后补 tabindex 让键盘可达。
  // 链接里的图片保留原导航行为,不接管。
  const zoomable = (t: EventTarget | null): t is HTMLImageElement =>
    t instanceof HTMLImageElement && !t.closest("a");
  const bodyHtml = typeof body === "object" && body.status === "ready" ? body.html : null;
  // React 19 按引用比较 dangerouslySetInnerHTML:每次渲染新建 {__html} 会重写 innerHTML,
  // 弹层开合/评论加载等重渲染都会重建正文 DOM(丢 tabindex、焦点无处可回),故按串记忆
  const bodyInner = useMemo(() => ({ __html: bodyHtml ?? "" }), [bodyHtml]);
  useEffect(() => {
    bodyRef.current?.querySelectorAll("img").forEach((img) => {
      if (zoomable(img)) img.tabIndex = 0;
    });
  }, [bodyHtml]);

  const openZoom = (img: HTMLImageElement) => {
    triggerRef.current = img;
    setZoom({ src: img.getAttribute("src") ?? "", alt: img.alt, full: false });
  };
  const onBodyClick = (e: MouseEvent<HTMLDivElement>) => {
    if (zoomable(e.target)) openZoom(e.target);
  };
  const onBodyKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if ((e.key === "Enter" || e.key === " ") && zoomable(e.target)) {
      e.preventDefault();
      openZoom(e.target);
    }
  };

  if (!meta) return <Navigate to="/blog" replace />;

  const activeBody = typeof body === "object" && body.slug === slug ? body : "loading";

  return (
    <PageTransition testId="page-note">
      <article className="note">
        <header className="note-head">
          <Link className="note-back" to="/blog">← 博客论坛</Link>
          <h1>{meta.title}</h1>
          <p className="note-meta">
            {meta.date}
            {meta.source !== "站内" ? ` · 首发于 ${meta.source}` : ""}
          </p>
        </header>
        {/* 正文为本人撰写、私仓审查签字后构建期编译的静态串:无用户输入,无注入面 */}
        {activeBody !== "loading" && activeBody.status === "ready" ? (
          <div
            ref={bodyRef}
            className="note-body"
            onClick={onBodyClick}
            onKeyDown={onBodyKeyDown}
            dangerouslySetInnerHTML={bodyInner}
          />
        ) : activeBody !== "loading" && activeBody.status === "error" ? (
          <p className="note-error">正文加载失败,请刷新重试</p>
        ) : (
          <p className="note-loading">加载中…</p>
        )}
        {meta.sourceUrl && (
          <footer className="note-foot">
            首发于{" "}
            <a href={meta.sourceUrl} target="_blank" rel="noopener noreferrer">
              {meta.source}
            </a>
            ,欢迎去原帖交流。
          </footer>
        )}
        {activeBody !== "loading" && activeBody.status === "ready" && (
          <NoteComments slug={slug} />
        )}
      </article>
      {/* portal 到 body:PageTransition 的 transform 会建层叠上下文,
          留在树内时 fixed 遮罩压不过全站顶栏 */}
      {zoom &&
        createPortal(
          <div
            className={`note-zoom${zoom.full ? " is-full" : ""}`}
            role="dialog"
            aria-modal="true"
            aria-label={zoom.alt}
            ref={dialogRef}
            onClick={closeZoom}
          >
            <button ref={closeRef} type="button" className="note-zoom-close" aria-label="关闭">
              ×
            </button>
            <button
              type="button"
              className="note-zoom-toggle"
              aria-pressed={zoom.full}
              aria-label="原尺寸"
              onClick={(e) => {
                e.stopPropagation();
                setZoom((z) => z && { ...z, full: !z.full });
              }}
            >
              <img src={zoom.src} alt={zoom.alt} />
            </button>
            <p className="note-zoom-hint">轻点图片切换原尺寸 · 点空白处关闭</p>
          </div>,
          document.body,
        )}
    </PageTransition>
  );
}
