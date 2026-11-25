import { useEffect, useState } from "react";
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

  const title = meta?.title;
  useEffect(() => {
    if (title) document.title = `王景宏 · 博客论坛 · ${title}`;
  }, [title]);

  useEffect(() => {
    let alive = true;
    setBody("loading"); // slug 切换即重置,不依赖 App 层 key 重挂载
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
          <div className="note-body" dangerouslySetInnerHTML={{ __html: activeBody.html }} />
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
    </PageTransition>
  );
}
