/** Hero 星座粒子的纯逻辑：创建/步进/连线，与画布解耦以便注入随机源与时钟做单测。 */

export interface Particle {
  x: number;
  y: number;
  vx: number;
  vy: number;
  /** 基速(环境漂移分量,创建时=初始速度):阻尼只收敛扰动、不吃基速,场才不会冻结 */
  bvx: number;
  bvy: number;
  r: number;
  gold: boolean;
}

export function createField(count: number, w: number, h: number, rand: () => number = Math.random): Particle[] {
  return Array.from({ length: count }, () => {
    const x = rand() * w;
    const y = rand() * h;
    const vx = (rand() - 0.5) * 0.45;
    const vy = (rand() - 0.5) * 0.45;
    // 半径/金点概率上调自 1.6+0.6 / 0.3(2026-07-28 用户反馈星空微弱)
    return { x, y, vx, vy, bvx: vx, bvy: vy, r: rand() * 2.2 + 0.8, gold: rand() < 0.35 };
  });
}

export function stepField(ps: Particle[], w: number, h: number, mouse: { x: number; y: number }, dt: number): void {
  const k = dt / 16.7; // 帧率无关：以 60fps 为基准折算
  for (const p of ps) {
    const dx = mouse.x - p.x;
    const dy = mouse.y - p.y;
    const d2 = dx * dx + dy * dy;
    if (d2 < 130 * 130 && d2 > 0) {
      const d = Math.sqrt(d2);
      p.vx += dx * 0.00004 * (130 - d) * k;
      p.vy += dy * 0.00004 * (130 - d) * k;
    }
    // 阻尼只衰减鼠标扰动分量(v-bv),基速永续——若等比阻尼整只 v,
    // 每粒子终身位移仅 ~35px,约 15s 后全场静止冻结
    p.vx = p.bvx + (p.vx - p.bvx) * 0.995;
    p.vy = p.bvy + (p.vy - p.bvy) * 0.995;
    p.x += p.vx * k;
    p.y += p.vy * k;
    if (p.x < 0) p.x += w;
    if (p.x > w) p.x -= w;
    if (p.y < 0) p.y += h;
    if (p.y > h) p.y -= h;
  }
}

/** 画布尺寸变化时按比例重分布粒子,防「0 高挂载/剧烈缩放后粒子堆死角落」。非法尺寸 no-op。 */
export function rescaleField(ps: Particle[], oldW: number, oldH: number, newW: number, newH: number): void {
  if (oldW <= 0 || oldH <= 0 || newW <= 0 || newH <= 0) return;
  const sx = newW / oldW;
  const sy = newH / oldH;
  for (const p of ps) {
    p.x *= sx;
    p.y *= sy;
  }
}

export function linkPairs(ps: Particle[], maxDist: number): Array<[number, number, number]> {
  const out: Array<[number, number, number]> = [];
  const m2 = maxDist * maxDist;
  for (let i = 0; i < ps.length; i++)
    for (let j = i + 1; j < ps.length; j++) {
      const dx = ps[i].x - ps[j].x;
      const dy = ps[i].y - ps[j].y;
      const d2 = dx * dx + dy * dy;
      if (d2 < m2) out.push([i, j, 1 - Math.sqrt(d2) / maxDist]);
    }
  return out;
}
