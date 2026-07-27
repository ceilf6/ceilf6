// 服务 /content/notes/*.md 的静态 import（vite-md-notes 插件产物）。
// 注意:import.meta.glob 不消费本 wildcard 声明(推断为 unknown)——
// glob 处须显式泛型,类型出口见 src/data/note-module.ts 的 NoteModule。
declare module "*.md" {
  export const meta: Record<string, string>;
  export const html: string;
}
