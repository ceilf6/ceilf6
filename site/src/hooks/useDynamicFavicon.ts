import { useEffect, useRef } from "react";
import type { Award } from "../data/awards";

/** 逐段迁移自旧 viewer.html 214–295 行的动态 favicon 逻辑：
    当前奖状缩略图画进 64px 方形画布作为标签页图标，离开/出错回落默认头像。 */

const DEFAULT_FAVICON = "/assets/Profile.jpg";
const FAVICON_SIZE = 64;

function applyFavicon(href: string) {
  const old = document.getElementById("favicon");
  const link = document.createElement("link");
  link.rel = "icon";
  link.id = "favicon";
  link.href = href;
  // 部分浏览器不响应 href 原地修改，整体换掉 link 更稳
  if (old) old.remove();
  document.head.appendChild(link);
}

// 把缩略图等比缩进 FAVICON_SIZE 的方形画布（留透明边），逐级减半保证缩放质量
function drawFaviconDataUrl(img: HTMLImageElement): string {
  const ratio = Math.min(
    FAVICON_SIZE / img.naturalWidth,
    FAVICON_SIZE / img.naturalHeight,
  );
  const w = Math.max(1, Math.round(img.naturalWidth * ratio));
  const h = Math.max(1, Math.round(img.naturalHeight * ratio));

  let src: CanvasImageSource = img;
  let sw = img.naturalWidth;
  let sh = img.naturalHeight;
  while (sw > w * 2 && sh > h * 2) {
    sw = Math.max(w, Math.round(sw / 2));
    sh = Math.max(h, Math.round(sh / 2));
    const step = document.createElement("canvas");
    step.width = sw;
    step.height = sh;
    const stepCtx = step.getContext("2d")!;
    stepCtx.imageSmoothingEnabled = true;
    stepCtx.imageSmoothingQuality = "high";
    stepCtx.drawImage(src, 0, 0, sw, sh);
    src = step;
  }

  const canvas = document.createElement("canvas");
  canvas.width = FAVICON_SIZE;
  canvas.height = FAVICON_SIZE;
  const ctx = canvas.getContext("2d")!;
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(
    src,
    Math.round((FAVICON_SIZE - w) / 2),
    Math.round((FAVICON_SIZE - h) / 2),
    w,
    h,
  );
  return canvas.toDataURL("image/png");
}

export function useDynamicFavicon(award: Pick<Award, "src" | "thumb"> | null) {
  // 快速连点切换时，用 token 丢弃迟到的旧图，避免图标和大图对不上（取代旧全局 faviconToken）
  const tokenRef = useRef(0);

  useEffect(() => {
    const token = ++tokenRef.current;
    if (!award) {
      applyFavicon(DEFAULT_FAVICON);
      return;
    }
    const source = award.thumb || award.src;
    // jsdom 无真实图片加载：onload/onerror 永不触发即零副作用；构造异常则降级直贴原图
    try {
      const loader = new Image();
      loader.decoding = "async";
      loader.onload = () => {
        if (token !== tokenRef.current) return;
        try {
          applyFavicon(drawFaviconDataUrl(loader));
        } catch {
          applyFavicon(source);
        }
      };
      loader.onerror = () => {
        if (token !== tokenRef.current) return;
        applyFavicon(DEFAULT_FAVICON);
      };
      loader.src = source;
    } catch {
      applyFavicon(source);
    }
  }, [award]);

  // 卸载：作废在途 loader 并恢复默认图标
  useEffect(() => {
    const ref = tokenRef;
    return () => {
      ++ref.current;
      applyFavicon(DEFAULT_FAVICON);
    };
  }, []);
}
