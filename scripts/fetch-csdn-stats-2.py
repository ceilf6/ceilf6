#!/usr/bin/env python3
"""
Fetch CSDN statistics (v2) and update data/csdn-stats.json
包含访问量统计
使用 cloudscraper 绕过 Cloudflare 保护
"""

import json
import re
import time
from datetime import datetime
from pathlib import Path

import cloudscraper
from bs4 import BeautifulSoup

# CSDN User ID
CSDN_USERNAME = "2301_78856868"

# CSDN Blog URL
CSDN_BLOG_URL = f"https://blog.csdn.net/{CSDN_USERNAME}"


def fetch_csdn_stats():
    """获取CSDN统计数据（包含访问量）- 使用 cloudscraper 绕过 Cloudflare"""
    max_retries = 3
    retry_delay = 5  # seconds

    # 创建 cloudscraper 实例
    scraper = cloudscraper.create_scraper(
        browser={
            'browser': 'chrome',
            'platform': 'darwin',
            'desktop': True
        }
    )

    for attempt in range(max_retries):
        try:
            if attempt > 0:
                print(f"Retry attempt {attempt + 1}/{max_retries} after {retry_delay}s delay...")
                time.sleep(retry_delay)
                # 每次重试创建新的 scraper 实例
                scraper = cloudscraper.create_scraper(
                    browser={
                        'browser': 'chrome',
                        'platform': 'darwin',
                        'desktop': True
                    }
                )

            print(f"Fetching {CSDN_BLOG_URL} ...")
            response = scraper.get(CSDN_BLOG_URL, timeout=30)
            response.raise_for_status()
            html_content = response.text

            # 检查是否被 Cloudflare 拦截
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
        print("Failed to fetch data. No updates made.")
        exit(1)


if __name__ == '__main__':
    main()
