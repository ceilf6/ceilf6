import { Link } from "react-router";
import { notes, type NoteMeta } from "../data/notes";
import "./NotesPreview.css";

/** 主页第四幕与 /blog 上层共用的札记卡列表;空列表渲染 null,
    文章未签字落地前站点外观与现状完全一致。
    max = 主页精选窗口(列表已按 date 倒序,slice 即取最新);/blog 不传 max 才是全集。 */
export function NotesPreview({
  heading,
  items = notes,
  max,
}: {
  heading: string;
  items?: NoteMeta[];
  max?: number;
}) {
  const shown = max ? items.slice(0, max) : items;
  if (shown.length === 0) return null;
  return (
    <section className="act act-notes" data-act-reveal>
      <h2 className="act-title">{heading}</h2>
      <div className="notes-grid">
        {shown.map((n) => (
          <Link key={n.slug} className="note-card" to={`/notes/${n.slug}`}>
            <span className="note-card-source">{n.source}</span>
            <h3>{n.title}</h3>
            <p>{n.summary}</p>
            <span className="note-card-date">{n.date}</span>
          </Link>
        ))}
      </div>
    </section>
  );
}
