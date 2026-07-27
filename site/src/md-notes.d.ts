// 给业务代码 import.meta.glob("/content/notes/*.md") 看的模块形状（vite-md-notes 插件产物）
declare module "*.md" {
  export const meta: Record<string, string>;
  export const html: string;
}
