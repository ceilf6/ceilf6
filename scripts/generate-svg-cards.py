#!/usr/bin/env python3
"""
Generate SVG cards for Blog and Vlog stats
"""

import json
from pathlib import Path


def format_number(num):
    """格式化数字"""
    if num >= 10000:
        return f"{num/10000:.1f}万"
    return f"{num:,}"


def generate_blog_card(stats):
    """生成Blog统计SVG卡片"""
    fans = format_number(stats.get('fans', 0))
    likes = format_number(stats.get('likes', 0))
    collect = format_number(stats.get('collect', 0))
    original = format_number(stats.get('original', 0))
    views = format_number(stats.get('views', 0))

    svg = f'''<svg width="450" height="200" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <style>
      .card {{ fill: #1A1B27; }}
      .title {{ fill: #70A5FE; font-size: 20px; font-weight: bold; font-family: 'Segoe UI', Ubuntu, Sans-Serif; }}
      .label {{ fill: #9f9f9f; font-size: 14px; font-family: 'Segoe UI', Ubuntu, Sans-Serif; }}
      .value {{ fill: #fff; font-size: 14px; font-weight: bold; font-family: 'Segoe UI', Ubuntu, Sans-Serif; }}
      .icon {{ opacity: 0.15; }}
    </style>
  </defs>

  <!-- Background -->
  <rect class="card" x="0" y="0" width="450" height="200" rx="10" />

  <!-- Title -->
  <text class="title" x="20" y="35">📝 Blog</text>

  <!-- Stats -->
  <text class="label" x="20" y="65">👥 粉丝:</text>
  <text class="value" x="100" y="65">{fans}</text>

  <text class="label" x="20" y="90">👍 点赞:</text>
  <text class="value" x="100" y="90">{likes}</text>

  <text class="label" x="20" y="115">⭐ 收藏:</text>
  <text class="value" x="100" y="115">{collect}</text>

  <text class="label" x="20" y="140">📄 原创:</text>
  <text class="value" x="100" y="140">{original}</text>

  <text class="label" x="20" y="165">👁️ 访问:</text>
  <text class="value" x="100" y="165">{views}</text>

  <!-- Icon Background -->
  <circle class="icon" cx="380" cy="100" r="50" fill="#70A5FE" />
  <text class="icon" x="360" y="120" font-size="50">📝</text>
</svg>'''

    return svg


def generate_vlog_card(stats):
    """生成Vlog统计SVG卡片"""
    follower = format_number(stats.get('follower', 0))
    views = format_number(stats.get('views', 0))
    likes = format_number(stats.get('likes', 0))

    svg = f'''<svg width="450" height="160" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <style>
      .card {{ fill: #1A1B27; }}
      .title {{ fill: #70A5FE; font-size: 20px; font-weight: bold; font-family: 'Segoe UI', Ubuntu, Sans-Serif; }}
      .label {{ fill: #9f9f9f; font-size: 14px; font-family: 'Segoe UI', Ubuntu, Sans-Serif; }}
      .value {{ fill: #fff; font-size: 14px; font-weight: bold; font-family: 'Segoe UI', Ubuntu, Sans-Serif; }}
      .icon {{ opacity: 0.15; }}
    </style>
  </defs>

  <!-- Background -->
  <rect class="card" x="0" y="0" width="450" height="160" rx="10" />

  <!-- Title -->
  <text class="title" x="20" y="35">🎬 Vlog</text>

  <!-- Stats -->
  <text class="label" x="20" y="70">👥 粉丝:</text>
  <text class="value" x="100" y="70">{follower}</text>

  <text class="label" x="20" y="100">▶️ 播放:</text>
  <text class="value" x="100" y="100">{views}</text>

  <text class="label" x="20" y="130">💖 获赞:</text>
  <text class="value" x="100" y="130">{likes}</text>

  <!-- Icon Background -->
  <circle class="icon" cx="380" cy="80" r="45" fill="#70A5FE" />
  <text class="icon" x="360" y="100" font-size="45">🎬</text>
</svg>'''

    return svg


def main():
    # 读取数据
    csdn_stats_file = Path(__file__).parent.parent / 'data' / 'csdn-stats.json'
    bilibili_stats_file = Path(__file__).parent.parent / 'data' / 'bilibili-stats.json'

    # 生成Blog卡片
    if csdn_stats_file.exists():
        with open(csdn_stats_file, 'r', encoding='utf-8') as f:
            csdn_stats = json.load(f)

        blog_svg = generate_blog_card(csdn_stats)
        blog_svg_file = Path(__file__).parent.parent / 'assets' / 'blog-card.svg'
        blog_svg_file.parent.mkdir(parents=True, exist_ok=True)

        with open(blog_svg_file, 'w', encoding='utf-8') as f:
            f.write(blog_svg)

        print("Blog card generated successfully!")

    # 生成Vlog卡片
    if bilibili_stats_file.exists():
        with open(bilibili_stats_file, 'r', encoding='utf-8') as f:
            bilibili_stats = json.load(f)

        vlog_svg = generate_vlog_card(bilibili_stats)
        vlog_svg_file = Path(__file__).parent.parent / 'assets' / 'vlog-card.svg'
        vlog_svg_file.parent.mkdir(parents=True, exist_ok=True)

        with open(vlog_svg_file, 'w', encoding='utf-8') as f:
            f.write(vlog_svg)

        print("Vlog card generated successfully!")


if __name__ == '__main__':
    main()
