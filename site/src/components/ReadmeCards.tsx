import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { readmeCards, type ReadmeCard } from "../data/site";
import { attachTilt } from "../fx/tilt";
import "./ReadmeCards.css";

type LoadState = "loading" | "loaded" | "error";

/** 旧站 setupReadmeCardLoading 的等价实现：类名沿用 is-loading/is-loaded/is-error，
    图片 opacity 由 CSS 按状态类驱动（旧站是 JS 写 inline style，视觉等价）。
    loader 节点始终挂载，靠 CSS 淡出；只有文案随状态切换，加载完即无「加载中」。 */
function Card({ card }: { card: ReadmeCard }) {
  const [state, setState] = useState<LoadState>("loading");
  const ref = useRef<HTMLAnchorElement>(null);

  // tilt 是纯视觉增强:href/顺序/external 语义零改动
  useEffect(() => (ref.current ? attachTilt(ref.current) : undefined), []);

  const content = (
    <>
      <span className="readme-card-loader" aria-hidden="true">
        {state === "loading" ? "加载中" : state === "error" ? "加载失败" : null}
      </span>
      <img
        src={card.img}
        alt={card.alt}
        width={340}
        height={200}
        onLoad={() => setState("loaded")}
        onError={() => setState("error")}
      />
    </>
  );

  const className = `readme-card is-${state}`;

  return card.external ? (
    <a ref={ref} className={className} href={card.href} target="_blank" rel="noopener noreferrer">
      {content}
    </a>
  ) : (
    <Link ref={ref} className={className} to={card.href}>
      {content}
    </Link>
  );
}

export function ReadmeCards() {
  return (
    <div className="readme-cards">
      {readmeCards.map((card) => (
        <Card key={card.href} card={card} />
      ))}
    </div>
  );
}
