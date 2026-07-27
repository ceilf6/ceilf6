/** Hero 星座粒子的纯逻辑：创建/步进/连线，与画布解耦以便注入随机源与时钟做单测。 */

export interface Particle {
  x: number;
  y: number;
  vx: number;
  vy: number;
  r: number;
  gold: boolean;
}

export function createField(count: number, w: number, h: number, rand: () => number = Math.random): Particle[] {
  return Array.from({ length: count }, () => ({
    x: rand() * w,
    y: rand() * h,
    vx: (rand() - 0.5) * 0.45,
    vy: (rand() - 0.5) * 0.45,
    r: rand() * 1.6 + 0.6,
    gold: rand() < 0.3,
  }));
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
    p.vx *= 0.995;
    p.vy *= 0.995;
    p.x += p.vx * k;
    p.y += p.vy * k;
    if (p.x < 0) p.x += w;
    if (p.x > w) p.x -= w;
    if (p.y < 0) p.y += h;
    if (p.y > h) p.y -= h;
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
