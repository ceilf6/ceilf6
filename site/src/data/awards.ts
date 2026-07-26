import raw from "./awards.json";

/** 与旧 resume-awards/images.js 同构；src/thumb 为部署后的绝对路径。
    width/height 由 site/scripts/update-image-metadata.mjs 维护，勿手改。 */
export interface Award {
  src: string;
  thumb: string;
  /** viewer 展示级渲染（长边 2000 jpeg，site/scripts/generate-display.mjs 维护）；原件走 src */
  display: string;
  alt: string;
  width: number;
  height: number;
  thumbWidth: number;
  thumbHeight: number;
}

export const awards: Award[] = raw;
