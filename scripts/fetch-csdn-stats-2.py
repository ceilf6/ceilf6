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

        # 使用正则表达式提取数据
        stats = {}

        # 提取总访问量
        # 匹配模式: <div class="user-profile-statistics-num"...>数字</div> <div class="user-profile-statistics-name"...>总访问量</div>
        views_match = re.search(
            r'<div[^>]*class="user-profile-statistics-num"[^>]*>([0-9,]+)</div>\s*<div[^>]*class="user-profile-statistics-name"[^>]*>总访问量</div>',
            html_content
        )
        if views_match:
            views_str = views_match.group(1).replace(',', '')
            stats['views'] = int(views_str)

        # 提取原创数量
        original_match = re.search(
            r'<div[^>]*class="user-profile-statistics-num"[^>]*>([0-9,]+)</div>\s*<div[^>]*class="user-profile-statistics-name"[^>]*>原创</div>',
            html_content
        )
        if original_match:
            original_str = original_match.group(1).replace(',', '')
            stats['original'] = int(original_str)

        # 提取粉丝数
        fans_match = re.search(
            r'<div[^>]*class="user-profile-statistics-num"[^>]*>([0-9,]+)</div>\s*<div[^>]*class="user-profile-statistics-name"[^>]*>粉丝</div>',
            html_content
        )
        if fans_match:
            fans_str = fans_match.group(1).replace(',', '')
            stats['fans'] = int(fans_str)

        # 提取点赞数
        # 匹配模式: 获得<span>数字</span>次点赞
        likes_match = re.search(r'获得<span>([0-9,]+)</span>次点赞', html_content)
        if likes_match:
            likes_str = likes_match.group(1).replace(',', '')
            stats['likes'] = int(likes_str)

        # 提取收藏数
        # 匹配模式: 获得<span>数字</span>次收藏
        collect_match = re.search(r'获得<span>([0-9,]+)</span>次收藏', html_content)
        if collect_match:
            collect_str = collect_match.group(1).replace(',', '')
            stats['collect'] = int(collect_str)

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
    """更新stats JSON文件，只有值>0时才覆盖"""
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

    # Update with new values only if > 0
    updated_fields = []
    for key, value in stats.items():
        if isinstance(value, int) and value > 0:
            existing_data[key] = value
            updated_fields.append(key)
        else:
            print(f"Skipping {key}: value {value} is not > 0")

    if not updated_fields:
        print("No valid stats to update (all values <= 0)")
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
