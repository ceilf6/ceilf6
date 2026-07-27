import { Link } from "react-router";
import { notes, type NoteMeta } from "../data/notes";
import "./NotesPreview.css";

/** 主页第四幕与 /blog 上层共用的札记卡列表;空列表渲染 null,
    文章未签字落地前站点外观与现状完全一致。 */
export function NotesPreview({
  heading,
  items = notes,
}: {
  heading: string;
  items?: NoteMeta[];
}) {
  if (items.length === 0) return null;
  return (
    <section className="act act-notes" data-act-reveal>
      <h2 className="act-title">{heading}</h2>
      <div className="notes-grid">
        {items.map((n) => (
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
