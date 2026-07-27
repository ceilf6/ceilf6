import { useEffect, useState } from "react";
import { Link, Navigate, useParams } from "react-router";
import { loadNoteHtml, notes } from "../data/notes";
import { PageTransition } from "../components/PageTransition";
import "./Note.css";

export default function Note() {
  const { slug = "" } = useParams();
  const meta = notes.find((n) => n.slug === slug);
  const [html, setHtml] = useState<string | null>(null);

  useEffect(() => {
    if (meta) document.title = `${meta.title} · 王景宏札记`;
  }, [meta]);

  useEffect(() => {
    let alive = true;
    const p = loadNoteHtml(slug);
    if (p) p.then((h) => alive && setHtml(h));
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
        {html ? (
          <div className="note-body" dangerouslySetInnerHTML={{ __html: html }} />
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
