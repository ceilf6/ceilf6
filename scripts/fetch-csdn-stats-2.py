#!/usr/bin/env python3
"""
Fetch CSDN statistics (v2) and update data/csdn-stats.json
包含访问量统计
优先使用环境变量 CSDN_COOKIES 携带真实会话 cookie（绕过 bot 检测），
否则回退到 cloudscraper 自动绕过。
"""

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

import requests
import cloudscraper
from bs4 import BeautifulSoup

# CSDN User ID
CSDN_USERNAME = "2301_78856868"

# CSDN Blog URL
CSDN_BLOG_URL = f"https://blog.csdn.net/{CSDN_USERNAME}"


def _parse_cookies(cookie_str: str) -> dict:
    """将 'key=val; key2=val2' 解析为字典。"""
    cookies = {}
    for part in cookie_str.split(';'):
        part = part.strip()
        if '=' in part:
            k, v = part.split('=', 1)
            cookies[k.strip()] = v.strip()
    return cookies


def _make_session(cookie_str: str | None):
    """根据是否有 cookie 字符串，返回 (session, use_cookies) 元组。"""
    if cookie_str:
        session = requests.Session()
        session.cookies.update(_parse_cookies(cookie_str))
        return session, True
    else:
        return cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'darwin', 'desktop': True}
        ), False


# 与 request.md 一致的浏览器请求头（不含 Cookie，由 session 携带）
_BROWSER_HEADERS = {
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Cache-Control': 'max-age=0',
    'Connection': 'keep-alive',
    'DNT': '1',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'cross-site',
    'Sec-Fetch-User': '?1',
    'Upgrade-Insecure-Requests': '1',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'sec-ch-ua': '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"macOS"',
}


# CSDN JSON API — 比 HTML 页走不同的 CDN 路径，在 GitHub Actions 环境下更易通过 WAF
_CSDN_API_URL = f"https://blog.csdn.net/community/home-api/v1/get-business-card?username={CSDN_USERNAME}"

_API_HEADERS = {
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Connection': 'keep-alive',
    'DNT': '1',
    'Referer': f'https://blog.csdn.net/{CSDN_USERNAME}',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'sec-ch-ua': '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"macOS"',
    'X-Requested-With': 'XMLHttpRequest',
}


def fetch_via_api(cookie_str: str | None) -> dict | None:
    """通过 CSDN JSON API 获取统计数据，成功返回 stats dict，失败返回 None。"""
    try:
        session = requests.Session()
        if cookie_str:
            session.cookies.update(_parse_cookies(cookie_str))
        resp = session.get(_CSDN_API_URL, headers=_API_HEADERS, timeout=30)
        resp.raise_for_status()
        body = resp.json()
        if body.get('code') != 200:
            print(f"API returned code={body.get('code')}: {body.get('msg', '')}")
            return None
        d = body.get('data', {})
        # 字段映射
        mapping = {
            'visitCount':    'views',
            'followerCount': 'fans',
            'likeCount':     'likes',
            'favoriteCount': 'collect',
            'blogCount':     'original',
        }
        stats = {}
        for api_key, stat_key in mapping.items():
            if api_key in d and d[api_key] is not None:
                stats[stat_key] = int(d[api_key])
        print(f"API fetch succeeded: {stats}")
        return stats if stats else None
    except Exception as e:
        print(f"API fetch failed: {e}")
        return None


def fetch_csdn_stats():
    """获取CSDN统计数据（包含访问量）。

    优先使用 JSON API（绕过 HTML 页 WAF 限制），失败再回退 HTML 抓取。
    """
    max_retries = 3
    retry_delay = 5  # seconds

    cookie_str = os.environ.get('CSDN_COOKIES', '').strip() or None
    if cookie_str:
        print("Using CSDN_COOKIES from environment variable.")
    else:
        print("CSDN_COOKIES not set, falling back to cloudscraper.")

    # ── 第一步：尝试 JSON API ──
    print(f"Trying CSDN API: {_CSDN_API_URL} ...")
    api_stats = fetch_via_api(cookie_str)
    if api_stats and len(api_stats) >= 3:
        return api_stats
    print("API fetch insufficient, falling back to HTML scraping...")


    session, use_cookies = _make_session(cookie_str)

    for attempt in range(max_retries):
        try:
            if attempt > 0:
                print(f"Retry attempt {attempt + 1}/{max_retries} after {retry_delay}s delay...")
                time.sleep(retry_delay)
                # 每次重试重建 session
                session, use_cookies = _make_session(cookie_str)

            print(f"Fetching {CSDN_BLOG_URL} ...")
            if use_cookies:
                response = session.get(CSDN_BLOG_URL, headers=_BROWSER_HEADERS, timeout=30)
            else:
                response = session.get(CSDN_BLOG_URL, timeout=30)
            response.raise_for_status()
            html_content = response.text

            # 检查是否被 Cloudflare / bot 检测拦截
            if 'Just a moment' in html_content or 'Checking your browser' in html_content:
                print(f"Cloudflare challenge detected on attempt {attempt + 1}")
                if attempt == max_retries - 1:
                    print("Failed to bypass Cloudflare protection.")
                    return None
                continue

            # 如果成功获取，跳出重试循环
            break

        except Exception as e:
            print(f"Error on attempt {attempt + 1}: {e}")
            if attempt == max_retries - 1:
                print("All retry attempts failed.")
                return None
            continue
    else:
        return None

    try:
        # Debug: Save HTML content to file for inspection
        debug_file = Path(__file__).parent.parent / 'StatRequest' / 'CSDN' / 'version2' / 'debug_csdn_page.html'
        debug_file.parent.mkdir(parents=True, exist_ok=True)
        with open(debug_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        print(f"Debug: HTML content saved to {debug_file}")
        print(f"Debug: HTML length = {len(html_content)} bytes")

        stats = {}
        soup = BeautifulSoup(html_content, 'html.parser')

        # ── 方式1: BeautifulSoup 解析 user-profile-statistics-num/name ──
        # 页面结构：<div class="user-profile-statistics-num">数值</div>
        #           <div class="user-profile-statistics-name">标签</div>
        label_map = {
            '总访问量': 'views',
            '原创': 'original',
            '粉丝': 'fans',
        }
        num_divs = soup.find_all('div', class_='user-profile-statistics-num')
        print(f"Debug: Found {len(num_divs)} user-profile-statistics-num divs")
        for num_div in num_divs:
            # 找紧跟的 sibling
            name_div = num_div.find_next_sibling('div', class_='user-profile-statistics-name')
            if name_div:
                label = name_div.get_text(strip=True)
                key = label_map.get(label)
                if key:
                    raw = num_div.get_text(strip=True).replace(',', '')
                    if raw.isdigit():
                        stats[key] = int(raw)
                        print(f"Debug: Parsed {key} = {stats[key]} (label='{label}')")

        # ── 方式2: 正则兜底（兼容新旧两种 HTML 格式） ──
        # 新格式：class 属性在前，后跟 data-v-* 等属性
        # 旧格式：<div class="user-profile-statistics-num">数字</div> 无额外属性
        _regex_patterns = {
            'views':    (r'总访问量', 'views'),
            'original': (r'原创',    'original'),
            'fans':     (r'粉丝',    'fans'),
        }
        for field, (label, key) in _regex_patterns.items():
            if key in stats:
                continue
            # 宽松写法：兼容 class 前后有其他属性、数字前后有空白
            m = re.search(
                r'class="user-profile-statistics-num"[^>]*>\s*([0-9,]+)\s*</div>\s*'
                r'<div[^>]*class="user-profile-statistics-name"[^>]*>\s*' + label + r'\s*</div>',
                html_content, re.UNICODE)
            if m:
                stats[key] = int(m.group(1).replace(',', ''))
                print(f"Debug: {key} via regex (new-format) = {stats[key]}")
                continue
            # 原始写法（旧格式保留）：<div[^>]*class=...>数字</div>
            m = re.search(
                r'<div[^>]*class="user-profile-statistics-num"[^>]*>([0-9,]+)</div>\s*'
                r'<div[^>]*class="user-profile-statistics-name"[^>]*>' + label + r'</div>',
                html_content, re.UNICODE)
            if m:
                stats[key] = int(m.group(1).replace(',', ''))
                print(f"Debug: {key} via regex (old-format) = {stats[key]}")
            else:
                print(f"Debug: {key} all regex patterns failed")

        # ── 点赞 / 收藏：个人成就区段文本 ──
        # 结构: <div class="aside-common-box-content-text">获得<span>N</span>次点赞</div>
        achievement_texts = soup.find_all('div', class_='aside-common-box-content-text')
        print(f"Debug: Found {len(achievement_texts)} aside-common-box-content-text divs")
        for div in achievement_texts:
            text = div.get_text(strip=True)
            span = div.find('span')
            if not span:
                continue
            val_str = span.get_text(strip=True).replace(',', '')
            if not val_str.isdigit():
                continue
            val = int(val_str)
            if '次点赞' in text and 'likes' not in stats:
                stats['likes'] = val
                print(f"Debug: Parsed likes = {val}")
            elif '次收藏' in text and 'collect' not in stats:
                stats['collect'] = val
                print(f"Debug: Parsed collect = {val}")

        # 正则兜底 likes/collect（新旧格式一致，均为原始正则）
        if 'likes' not in stats:
            m = re.search(r'获得<span>([0-9,]+)</span>次点赞', html_content, re.UNICODE)
            if not m:
                # 兼容 span 含其他属性的情况
                m = re.search(r'获得<span[^>]*>([0-9,]+)</span>次点赞', html_content, re.UNICODE)
            if m:
                stats['likes'] = int(m.group(1).replace(',', ''))
                print(f"Debug: likes via regex fallback = {stats['likes']}")
            else:
                print("Debug: likes all regex patterns failed")
        if 'collect' not in stats:
            m = re.search(r'获得<span>([0-9,]+)</span>次收藏', html_content, re.UNICODE)
            if not m:
                m = re.search(r'获得<span[^>]*>([0-9,]+)</span>次收藏', html_content, re.UNICODE)
            if m:
                stats['collect'] = int(m.group(1).replace(',', ''))
                print(f"Debug: collect via regex fallback = {stats['collect']}")
            else:
                print("Debug: collect all regex patterns failed")

        print(f"Successfully fetched CSDN stats:")
        print(f"Views: {stats.get('views', 'N/A')}")
        print(f"Original: {stats.get('original', 'N/A')}")
        print(f"Fans: {stats.get('fans', 'N/A')}")
        print(f"Likes: {stats.get('likes', 'N/A')}")
        print(f"Collect: {stats.get('collect', 'N/A')}")

        return stats

    except Exception as e:
        print(f"Exception when fetching CSDN stats: {e}")
        import traceback
        traceback.print_exc()
        return None


def update_stats_file(stats):
    """更新stats JSON文件，只有当新值>=旧值时才覆盖"""
    if not stats:
        print("No stats to update")
        return False

    stats_file = Path(__file__).parent.parent / 'data' / 'csdn-stats.json'

    # Read existing data
    if stats_file.exists():
        with open(stats_file, 'r', encoding='utf-8') as f:
            existing_data = json.load(f)
    else:
        existing_data = {}

    # Check for data regression first
    has_regression = False
    regression_details = []

    for key, value in stats.items():
        if isinstance(value, int):
            existing_value = existing_data.get(key, 0)
            if value < existing_value:
                has_regression = True
                regression_details.append(f"{key}: {value} < {existing_value}")

    # If any data regressed, fail immediately
    if has_regression:
        print(f"❌ Data regression detected:")
        for detail in regression_details:
            print(f"  - {detail}")
        print("\nThis usually indicates:")
        print("  1. Network error or Cloudflare blocking")
        print("  2. CSDN page structure changed")
        print("  3. Data fetching failed")
        exit(1)

    # Update with new values only if >= existing value
    updated_fields = []
    for key, value in stats.items():
        if isinstance(value, int):
            existing_value = existing_data.get(key, 0)
            if value >= existing_value:
                existing_data[key] = value
                updated_fields.append(key)

    if not updated_fields:
        print("No stats to update (all new values == existing values)")
        return False

    existing_data['last_updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Write back to file
    stats_file.parent.mkdir(parents=True, exist_ok=True)
    with open(stats_file, 'w', encoding='utf-8') as f:
        json.dump(existing_data, f, ensure_ascii=False, indent=2)

    print(f"\nStats file updated successfully!")
    print(f"Updated fields: {', '.join(updated_fields)}")
    print(f"Last Updated: {existing_data['last_updated']}")
    return True


def main():
    print("Fetching CSDN statistics (v2 with views)...")

    # Fetch data
    stats = fetch_csdn_stats()

    # Update file
    if stats and len(stats) > 0:
        update_stats_file(stats)
    else:
        print("⚠️  Failed to fetch CSDN data (likely network block on GitHub Actions IPs). No updates made.")
        # 不使用 exit(1)，避免 workflow 因 CSDN 网络封锁而整体失败
        # 已有数据保持不变，下次 workflow 触发时再重试
        exit(0)


if __name__ == '__main__':
    main()
