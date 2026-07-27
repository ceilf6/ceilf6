import { useEffect, useState } from "react";
import { Link, Navigate, useParams } from "react-router";
import { loadNoteHtml, notes } from "../data/notes";
import { PageTransition } from "../components/PageTransition";
import "./Note.css";

/** 正文三态(对齐 Viewer 惯例):原子部署后旧 index.html 拉新 hash chunk 404 时必须落错误态,不许永久「加载中」 */
type NoteBody = "loading" | "error" | { html: string };

export default function Note() {
  const { slug = "" } = useParams();
  const meta = notes.find((n) => n.slug === slug);
  const [body, setBody] = useState<NoteBody>("loading");

  const title = meta?.title;
  useEffect(() => {
    if (title) document.title = `${title} · 王景宏札记`;
  }, [title]);

  useEffect(() => {
    let alive = true;
    setBody("loading"); // slug 切换即重置,不依赖 App 层 key 重挂载
    const p = loadNoteHtml(slug);
    if (p) {
      p.then(
        (h) => alive && setBody({ html: h }),
        () => alive && setBody("error"),
      );
    }
    return () => {
      alive = false;
    };
  }, [slug]);

  if (!meta) return <Navigate to="/blog" replace />;

  return (
    <PageTransition testId="page-note">
      <article className="note">
        <header className="note-head">
          <Link className="note-back" to="/blog">← 札记</Link>
          <h1>{meta.title}</h1>
          <p className="note-meta">
            {meta.date}
            {meta.source !== "站内" ? ` · 首发于 ${meta.source}` : ""}
          </p>
        </header>
        {/* 正文为本人撰写、私仓审查签字后构建期编译的静态串:无用户输入,无注入面 */}
        {typeof body === "object" ? (
          <div className="note-body" dangerouslySetInnerHTML={{ __html: body.html }} />
        ) : body === "error" ? (
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
      </article>
    </PageTransition>
  );
}
