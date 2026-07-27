/** /content/notes/*.md 经 vite-md-notes 插件编译后的模块形状。
    import.meta.glob 不消费 ambient wildcard 声明(推断为 unknown),
    glob 处须显式泛型:import.meta.glob<NoteModule>("/content/notes/*.md", …)。
    meta 必含 title/date/summary(插件构建期守卫保证)。 */
export interface NoteModule {
  meta: Record<string, string>;
  html: string;
}
