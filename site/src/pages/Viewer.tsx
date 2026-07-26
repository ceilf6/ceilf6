import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { awards } from "../data/awards";
import { useDynamicFavicon } from "../hooks/useDynamicFavicon";
import { PageTransition } from "../components/PageTransition";
import "./Viewer.css";

/** ?img=N 是对外契约（README 深链 0 基索引）：非纯数字或越界一律 -1 → 错误态 */
function parseIndex(raw: string | null): number {
  if (raw === null || !/^\d+$/.test(raw)) return -1;
  const n = Number(raw);
  return n >= 0 && n < awards.length ? n : -1;
}

export default function Viewer() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const index = parseIndex(params.get("img"));
  const award = index >= 0 ? awards[index] : null;
  const [imgState, setImgState] = useState<"loading" | "loaded" | "error">("loading");
  const touchStart = useRef({ x: 0, y: 0 });

  const show = (i: number) => {
    setImgState("loading");
    setParams({ img: String(i) }, { replace: true }); // 对齐旧站 history.replaceState
  };
  // 错误态（index=-1）也可导航：对齐旧站从 currentIndex=-1 出发 prev→末张、next→0
  const prev = () => show(index <= 0 ? awards.length - 1 : index - 1);
  const next = () => show(index >= awards.length - 1 ? 0 : index + 1);
  const close = () => navigate("/"); // SPA 内关闭 = 回主页（取代旧站 window.close 分支）

  useDynamicFavicon(award);

  useEffect(() => {
    if (award) document.title = `${award.alt} - 查看图片`;
  }, [award]);

  // 关键：不带依赖数组、每渲染重绑——react-router v8 非 data-router 模式下
  // useNavigate/setParams 引用不稳定，锁死依赖会产生过期闭包（P8 评审已确认）
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
      else if (e.key === "ArrowLeft") prev();
      else if (e.key === "ArrowRight") next();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  });

  // 触摸滑动同理每渲染重绑；起点存 ref 跨渲染保留。
  // 阈值与 passive:true 照抄旧 viewer.html 393–419 行（监听挂 document，旧站如此）
  useEffect(() => {
    const onTouchStart = (e: TouchEvent) => {
      touchStart.current = { x: e.touches[0].clientX, y: e.touches[0].clientY };
    };
    const onTouchEnd = (e: TouchEvent) => {
      const dx = e.changedTouches[0].clientX - touchStart.current.x;
      const dy = e.changedTouches[0].clientY - touchStart.current.y;
      // 水平滑动距离 > 50px 且水平位移大于垂直位移才触发
      if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy)) {
        if (dx < 0) {
          next();
        } else {
          prev();
        }
      }
    };
    document.addEventListener("touchstart", onTouchStart, { passive: true });
    document.addEventListener("touchend", onTouchEnd, { passive: true });
    return () => {
      document.removeEventListener("touchstart", onTouchStart);
      document.removeEventListener("touchend", onTouchEnd);
    };
  });

  const showError = !award || imgState === "error";
  const showLoading = award !== null && imgState === "loading";

  return (
    <PageTransition testId="page-viewer">
      <div className="viewer-screen">
        <button
          className="nav-btn prev"
          title="上一张 (←)"
          onClick={(e) => {
            e.stopPropagation();
            prev();
          }}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M15 18l-6-6 6-6" />
          </svg>
        </button>
        <button
          className="nav-btn next"
          title="下一张 (→)"
          onClick={(e) => {
            e.stopPropagation();
            next();
          }}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M9 18l6-6-6-6" />
          </svg>
        </button>

        <div className="viewer">
          {award && showLoading && (
            /* 渐进加载：缩略图（画廊里大概率已有缓存）先顶上，展示图到位后替换 */
            <img
              className="viewer-preview"
              src={award.thumb}
              alt=""
              aria-hidden="true"
            />
          )}
          {award && (
            <img
              src={award.display}
              alt={award.alt}
              style={{ display: imgState === "loaded" ? "block" : "none" }}
              onLoad={() => setImgState("loaded")}
              onError={() => setImgState("error")}
              onClick={close}
            />
          )}
          {showLoading && <div className="loading">加载奖状中</div>}
          {showError && <div className="error">图片未找到</div>}
        </div>
        {award && imgState === "loaded" && (
          <a
            className="original-link"
            href={award.src}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
          >
            查看原件
          </a>
        )}
      </div>
    </PageTransition>
  );
}
