/** 主页 README 卡片区（旧 index.html 的 4 张卡）。
    svg 为 bot 持续更新的部署路径，必须运行时加载、禁止构建期打包。 */
export interface ReadmeCard {
  href: string;
  external: boolean;
  img: string;
  alt: string;
}

export const readmeCards: ReadmeCard[] = [
  {
    href: "https://github.com/ceilf6",
    external: true,
    img: "/assets/github-stats-card.svg",
    alt: "Stats",
  },
  { href: "/blog", external: false, img: "/assets/blog-card.svg", alt: "Blog" },
  { href: "/vlog", external: false, img: "/assets/vlog-card.svg", alt: "Vlog" },
  {
    href: "https://huggingface.co/ceilf6",
    external: true,
    img: "/assets/huggingface-card.svg",
    alt: "Hugging Face",
  },
];

export const ICP = { text: "浙ICP备2026055968号-1", href: "https://beian.miit.gov.cn/" };
