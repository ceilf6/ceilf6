#!/usr/bin/env python3
"""
Fetch CSDN statistics and update data/csdn-stats.json
"""

import json
import re
import requests
from datetime import datetime
from pathlib import Path

# CSDN User ID
CSDN_USERNAME = "2301_78856868"

# CSDN Blog URL
CSDN_BLOG_URL = f"https://blog.csdn.net/{CSDN_USERNAME}"

# Headers for requests
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
}


def fetch_csdn_stats():
    """获取CSDN统计数据"""
    try:
        response = requests.get(CSDN_BLOG_URL, headers=HEADERS, timeout=15)
        response.raise_for_status()
        html_content = response.text

        # 使用正则表达式提取数据
        stats = {}

        # 提取原创数量
        original_match = re.search(r'<dt>原创</dt>\s*</a>\s*</dl>\s*<dl[^>]*>\s*<dd>(\d+)</dd>\s*<dt>点赞</dt>', html_content, re.DOTALL)
        if original_match:
            stats['original'] = int(original_match.group(1))
        else:
            # 备用方案
            original_match2 = re.search(r'<dd><span[^>]*>(\d+)</span></dd>\s*<dt>原创</dt>', html_content)
            if original_match2:
                stats['original'] = int(original_match2.group(1))

        # 提取点赞数
        likes_match = re.search(r'<dd>(\d+)</dd>\s*<dt>点赞</dt>', html_content)
        if likes_match:
            stats['likes'] = int(likes_match.group(1))

        # 提取收藏数
        collect_match = re.search(r'<dd>(\d+)</dd>\s*<dt>收藏</dt>', html_content)
        if collect_match:
            stats['collect'] = int(collect_match.group(1))

        # 提取粉丝数
        fans_match = re.search(r'<dd><span id="fan">(\d+)</span></dd>\s*<dt>粉丝</dt>', html_content)
        if fans_match:
            stats['fans'] = int(fans_match.group(1))

        print(f"Successfully fetched CSDN stats:")
        print(f"Original: {stats.get('original', 'N/A')}")
        print(f"Likes: {stats.get('likes', 'N/A')}")
        print(f"Collect: {stats.get('collect', 'N/A')}")
        print(f"Fans: {stats.get('fans', 'N/A')}")

        return stats

    except Exception as e:
        print(f"Exception when fetching CSDN stats: {e}")
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
    print("Fetching CSDN statistics...")

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
