import raw from "./awards.json";

/** 与旧 resume-awards/images.js 同构；src/thumb 为部署后的绝对路径。
    width/height 由 site/scripts/update-image-metadata.mjs 维护，勿手改。 */
export interface Award {
  src: string;
  thumb: string;
  alt: string;
  width: number;
  height: number;
  thumbWidth: number;
  thumbHeight: number;
}

export const awards: Award[] = raw;
