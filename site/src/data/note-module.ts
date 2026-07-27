/** /content/notes/*.md 经 vite-md-notes 插件编译后的模块形状。
    import.meta.glob 不消费 ambient wildcard 声明(推断为 unknown),
    glob 处须显式泛型:import.meta.glob<NoteModule>("/content/notes/*.md", …)。
    title/date/summary 是插件构建期守卫保证的硬契约,类型如实陈述为必填;
    其余键(source/sourceUrl 等)可缺席——Partial 使其读出 string|undefined,
    消费端的 ?? 兜底才不会沦为类型死代码。 */
export interface NoteModule {
  meta: { title: string; date: string; summary: string } & Partial<Record<string, string>>;
  html: string;
}
