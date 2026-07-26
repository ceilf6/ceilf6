import type { ReactNode } from "react";

/** 一张平台卡：文案 + 外链 + 品牌三色（注入 CSS 自定义属性）+ 内联 logo。
    logo 的 SVG 全部原样取自旧 blog.html / vlog.html 的 <span class="logo">，
    只按 JSX 要求把 stroke-width/stroke-linecap 改成驼峰，坐标与色值一字未动。 */
export interface PlatformEntry {
  index: string;
  name: string;
  handle: string;
  url: string;
  ariaLabel: string;
  brand: string;
  brandRgb: string;
  brand2Rgb: string;
  footText: string;
  logo: ReactNode;
}

export interface StageData {
  eyebrow: string;
  headline: string;
  subtitle: string;
  docTitle: string;
  platforms: PlatformEntry[];
}

export const blogStage: StageData = {
  eyebrow: "ceilf6 · blog",
  headline: "看看我的博客",
  subtitle: "挑一个平台，去读我写的技术文字与折腾笔记",
  docTitle: "看看我的博客 · ceilf6",
  platforms: [
    {
      index: "01",
      name: "LINUX DO",
      handle: "@ceilf6",
      url: "https://linux.do/u/ceilf6/summary",
      ariaLabel: "前往 LINUX DO 主页",
      brand: "#ffb003",
      brandRgb: "255, 176, 3",
      brand2Rgb: "86, 227, 207",
      footText: "前往主页",
      logo: (
        <svg viewBox="0 0 48 48">
          <circle cx="24" cy="24" r="21" fill="#1c1c1e" />
          <circle cx="24" cy="24" r="13" fill="#fff" />
          <path d="M11 24a13 13 0 0 1 26 0z" fill="#ffb003" />
          <path d="M11 24a13 13 0 0 0 26 0z" fill="#1c1c1e" />
        </svg>
      ),
    },
    {
      index: "02",
      name: "CSDN",
      handle: "2301_78856868",
      url: "https://blog.csdn.net/2301_78856868",
      ariaLabel: "前往 CSDN 博客主页",
      brand: "#fc5531",
      brandRgb: "252, 85, 49",
      brand2Rgb: "255, 178, 98",
      footText: "前往博客",
      logo: (
        <svg viewBox="0 0 48 48">
          <circle cx="24" cy="24" r="21" fill="#fc5531" />
          <path
            d="M30.5 17.4c-1.7-1-3.8-1.6-6.2-1.6-6 0-10.3 3.6-10.3 8.5s4.1 8.3 10.1 8.3c2.5 0 4.7-.6 6.5-1.7l-1.1-3.5c-1.3.8-2.9 1.3-4.7 1.3-3.3 0-5.7-1.8-5.7-4.5s2.3-4.6 5.8-4.6c1.7 0 3.2.4 4.4 1.1l1.2-3.1z"
            fill="#fff"
          />
        </svg>
      ),
    },
  ],
};

export const vlogStage: StageData = {
  eyebrow: "ceilf6 · vlog",
  headline: "看看我的视频",
  subtitle: "挑一个平台，去看我最近在拍的东西",
  docTitle: "看看我的视频 · ceilf6",
  platforms: [
    {
      index: "01",
      name: "抖音",
      handle: "TIKTOK",
      url: "https://www.douyin.com/user/MS4wLjABAAAA1y3YuKPCNetqkJ0FC20HMHXx7lz_T1pQsgvloOaZn-Y",
      ariaLabel: "前往抖音主页",
      brand: "#25f4ee",
      brandRgb: "37, 244, 238",
      brand2Rgb: "254, 44, 85",
      footText: "前往主页",
      logo: (
        <svg viewBox="0 0 24 24">
          <path
            d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"
            fill="#25f4ee"
            transform="translate(-1.1 1.1)"
          />
          <path
            d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"
            fill="#fe2c55"
            transform="translate(1.1 -1.1)"
          />
          <path
            d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"
            fill="#eef4ff"
          />
        </svg>
      ),
    },
    {
      index: "02",
      name: "哔哩哔哩",
      handle: "BILIBILI",
      url: "https://space.bilibili.com/3546602400647622",
      ariaLabel: "前往 Bilibili 主页",
      brand: "#fb7299",
      brandRgb: "251, 114, 153",
      brand2Rgb: "0, 174, 236",
      footText: "前往主页",
      logo: (
        <svg viewBox="0 0 48 48" fill="none">
          <path
            d="M16 6 L22 13 M32 6 L26 13"
            stroke="#fb7299"
            strokeWidth="3"
            strokeLinecap="round"
          />
          <rect x="7" y="13" width="34" height="26" rx="8" fill="#fb7299" />
          <rect
            x="15.4"
            y="22"
            width="3.6"
            height="7.4"
            rx="1.8"
            fill="#0c1730"
          />
          <rect
            x="29"
            y="22"
            width="3.6"
            height="7.4"
            rx="1.8"
            fill="#0c1730"
          />
        </svg>
      ),
    },
  ],
};
