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

/** 卡片区下方的 harness 看板导流横幅：静态文案保底，取到 /harness/data.json
    后升级为实时线程数与机审轮次。看板是独立静态页（不在 SPA 路由内），
    必须用原生 <a> 整页跳转，不能走 react-router Link。 */
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
        {stats
          ? `${stats.threads} 条交付线程 · 机审 CR 累计 ${stats.crRounds} 轮`
          : "飞书机器人接需求 · TDD 红绿纪律 · 对抗式机审 CR · 人工闸门"}
      </span>
      <span className="harness-banner-arrow" aria-hidden="true">
        →
      </span>
    </a>
  );
}
