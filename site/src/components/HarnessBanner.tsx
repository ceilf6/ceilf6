import { useEffect, useState } from "react";
import "./HarnessBanner.css";

interface HarnessStats {
  threads: number;
  crRounds: number;
}

interface HarnessThread {
  archived?: boolean;
  cr_rounds?: number;
}

/** 卡片区面板的页脚工艺线：流程文案常驻（与看板页阶段词表一致），
    取到 /harness/data.json 后追加实时数字胶囊。看板是独立静态页
    （不在 SPA 路由内），必须用原生 <a> 整页跳转，不能走 react-router Link。 */
export function HarnessBanner() {
  const [stats, setStats] = useState<HarnessStats | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    fetch("/harness/data.json", { signal: ctrl.signal })
      .then((r) => (r.ok ? r.json() : null))
      .then((d: { threads?: HarnessThread[] } | null) => {
        if (!d || !Array.isArray(d.threads)) return;
        const active = d.threads.filter((t) => !t.archived);
        setStats({
          threads: active.length,
          crRounds: d.threads.reduce((n, t) => n + (t.cr_rounds ?? 0), 0),
        });
      })
      .catch(() => {});
    return () => ctrl.abort();
  }, []);

  return (
    <a className="harness-banner" href="/harness/">
      <span className="harness-banner-dot" aria-hidden="true" />
      <span className="harness-banner-title">harness 线程看板</span>
      <span className="harness-banner-desc">
        飞书机器人接需求 · SDD 计划门 · TDD 红绿纪律 · 对抗式机审 CR · 人工闸门
      </span>
      {stats ? (
        <span className="harness-banner-live">
          {stats.threads} 条线程 · 机审 {stats.crRounds} 轮
        </span>
      ) : null}
      <span className="harness-banner-arrow" aria-hidden="true">
        →
      </span>
    </a>
  );
}
