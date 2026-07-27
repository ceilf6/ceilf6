import { useLayoutEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { awards, type Award } from "../data/awards";
import "./WaterfallGallery.css";

const ROW_GAP = 24; // 与旧站 resizeCard 的 +24 一致（gap 补偿）

type LoadState = "loading" | "loaded" | "error";

/** 旧站 getDisplaySize/resizeCard/reserveCardSpace 的等价实现：
    span 由「manifest 尺寸比 × 容器实宽」算出，manifest 恒有缩略图尺寸（P4 测试保证），
    因此不必等 img onload 再用 naturalWidth 兜底重算；窗口 resize 监听换成 ResizeObserver。
    loader 节点常驻，只有文案随状态切换，靠 CSS 淡出（与 ReadmeCards 同款处理）。 */
function GalleryCard({ award, index }: { award: Award; index: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<LoadState>("loading");
  const navigate = useNavigate();

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const apply = () => {
      const ratio =
        (award.thumbHeight || award.height) / (award.thumbWidth || award.width);
      el.style.gridRowEnd = `span ${Math.ceil(el.offsetWidth * ratio + ROW_GAP)}`;
    };
    apply();
    const ro = new ResizeObserver(apply);
    ro.observe(el);
    return () => ro.disconnect();
  }, [award]);

  return (
    <div
      ref={ref}
      className={`card is-${state}`}
      role="button"
      tabIndex={0}
      aria-label={`查看证书：${award.alt}`}
      style={{ aspectRatio: `${award.thumbWidth} / ${award.thumbHeight}` }}
      onClick={() => navigate(`/viewer?img=${index}`)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          navigate(`/viewer?img=${index}`);
        }
      }}
    >
      <div className="card-loader" aria-hidden="true">
        {state === "error" ? "加载失败" : state === "loading" ? "加载中" : null}
      </div>
      <img
        alt={award.alt}
        /* 首屏前三张 eager+首张高优先级：lazy 会被浏览器降权，拖累 LCP */
        loading={index < 3 ? "eager" : "lazy"}
        fetchPriority={index === 0 ? "high" : undefined}
        decoding="async"
        src={award.thumb || award.src}
        onLoad={() => setState("loaded")}
        onError={() => setState("error")}
      />
    </div>
  );
}

export function WaterfallGallery() {
  return (
    <div className="gallery waterfall active">
      {awards.map((a, i) => (
        <GalleryCard key={a.src} award={a} index={i} />
      ))}
    </div>
  );
}
