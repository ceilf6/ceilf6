#!/usr/bin/env python3
"""
Fetch CSDN statistics (v2) and update data/csdn-stats.json
包含访问量统计
"""

import json
import re
import requests
import time
from datetime import datetime
from pathlib import Path

# CSDN User ID
CSDN_USERNAME = "2301_78856868"

# CSDN Blog URL
CSDN_BLOG_URL = f"https://blog.csdn.net/{CSDN_USERNAME}"

# Headers for requests - 更完整的浏览器模拟
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Cache-Control': 'max-age=0',
}


def fetch_csdn_stats():
    """获取CSDN统计数据（包含访问量）- 带重试机制"""
    max_retries = 3
    retry_delay = 5  # seconds

    for attempt in range(max_retries):
        try:
            if attempt > 0:
                print(f"Retry attempt {attempt + 1}/{max_retries} after {retry_delay}s delay...")
                time.sleep(retry_delay)

            response = requests.get(CSDN_BLOG_URL, headers=HEADERS, timeout=15)
            response.raise_for_status()
            html_content = response.text

            # 如果成功获取，跳出重试循环
            break

        except requests.exceptions.HTTPError as e:
            print(f"HTTP Error on attempt {attempt + 1}: {e}")
            if attempt == max_retries - 1:
                # 最后一次尝试失败，返回 None
                print("All retry attempts failed.")
                return None
            continue
        except requests.exceptions.RequestException as e:
            print(f"Request Error on attempt {attempt + 1}: {e}")
            if attempt == max_retries - 1:
                print("All retry attempts failed.")
                return None
            continue
    else:
        # 不应该到这里，但以防万一
        return None

    try:

        # 使用正则表达式提取数据
        stats = {}

        # 提取总访问量
        # 匹配模式: <span class="user-profile-statistics-num">数字</span>...<div class="user-profile-statistics-name">总访问量</div>
        views_match = re.search(
            r'<span[^>]*class="user-profile-statistics-num"[^>]*>([0-9,]+)</span>.*?<div[^>]*class="user-profile-statistics-name"[^>]*>总访问量</div>',
            html_content,
            re.DOTALL
        )
        if views_match:
            views_str = views_match.group(1).replace(',', '')
            stats['views'] = int(views_str)

        # 提取原创数量
        # 匹配模式: <div class="user-profile-statistics-num">数字</div>...<div class="user-profile-statistics-name">原创</div>
        original_match = re.search(
            r'<div[^>]*class="user-profile-statistics-num"[^>]*>([0-9,]+)</div>.*?<div[^>]*class="user-profile-statistics-name"[^>]*>原创</div>',
            html_content,
            re.DOTALL
        )
        if original_match:
            original_str = original_match.group(1).replace(',', '')
            stats['original'] = int(original_str)

        # 提取粉丝数
        # 匹配模式: <div class="user-profile-statistics-num">数字</div>...<div class="user-profile-statistics-name">粉丝</div>
        fans_match = re.search(
            r'<div[^>]*class="user-profile-statistics-num"[^>]*>([0-9,]+)</div>.*?<div[^>]*class="user-profile-statistics-name"[^>]*>粉丝</div>',
            html_content,
            re.DOTALL
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
    """更新stats JSON文件"""
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

    # Update with new values
    existing_data.update(stats)
    existing_data['last_updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Write back to file
    stats_file.parent.mkdir(parents=True, exist_ok=True)
    with open(stats_file, 'w', encoding='utf-8') as f:
        json.dump(existing_data, f, ensure_ascii=False, indent=2)

    print(f"\nStats file updated successfully!")
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
