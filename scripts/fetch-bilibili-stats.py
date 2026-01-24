#!/usr/bin/env python3
"""
Fetch Bilibili statistics and update data/bilibili-stats.json
"""

import json
import requests
from datetime import datetime
from pathlib import Path

# Bilibili User ID
BILIBILI_UID = "3546602400647622"

# API Endpoints
FOLLOWER_API = f"https://api.bilibili.com/x/relation/stat?vmid={BILIBILI_UID}&web_location=333.1387"
STATS_API = f"https://api.bilibili.com/x/space/upstat?mid={BILIBILI_UID}&web_location=333.1387"

# Headers for requests
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
    'Accept': '*/*',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Origin': 'https://space.bilibili.com',
    'Referer': f'https://space.bilibili.com/{BILIBILI_UID}',
}


def fetch_follower_count():
    """获取粉丝数"""
    try:
        response = requests.get(FOLLOWER_API, headers=HEADERS, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data.get('code') == 0:
            return data.get('data', {}).get('follower', 0)
        else:
            print(f"Error fetching follower count: {data.get('message')}")
            return None
    except Exception as e:
        print(f"Exception when fetching follower count: {e}")
        return None


def fetch_views_and_likes():
    """获取播放数和获赞数"""
    try:
        response = requests.get(STATS_API, headers=HEADERS, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data.get('code') == 0:
            stats_data = data.get('data', {})
            views = stats_data.get('archive', {}).get('view', 0)
            likes = stats_data.get('likes', 0)
            return views, likes
        else:
            print(f"Error fetching views and likes: {data.get('message')}")
            return None, None
    except Exception as e:
        print(f"Exception when fetching views and likes: {e}")
        return None, None


def update_stats_file(follower, views, likes):
    """更新stats JSON文件"""
    stats_file = Path(__file__).parent.parent / 'data' / 'bilibili-stats.json'

    # Read existing data
    if stats_file.exists():
        with open(stats_file, 'r', encoding='utf-8') as f:
            existing_data = json.load(f)
    else:
        existing_data = {}

    # Update with new values (only if successfully fetched)
    if follower is not None:
        existing_data['follower'] = follower
    if views is not None:
        existing_data['views'] = views
    if likes is not None:
        existing_data['likes'] = likes

    existing_data['last_updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Write back to file
    stats_file.parent.mkdir(parents=True, exist_ok=True)
    with open(stats_file, 'w', encoding='utf-8') as f:
        json.dump(existing_data, f, ensure_ascii=False, indent=2)

    print(f"Stats updated successfully!")
    print(f"Follower: {existing_data.get('follower', 'N/A')}")
    print(f"Views: {existing_data.get('views', 'N/A')}")
    print(f"Likes: {existing_data.get('likes', 'N/A')}")
    print(f"Last Updated: {existing_data['last_updated']}")


def main():
    print("Fetching Bilibili statistics...")

    # Fetch data
    follower = fetch_follower_count()
    views, likes = fetch_views_and_likes()

    # Update file
    if follower is not None or views is not None or likes is not None:
        update_stats_file(follower, views, likes)
    else:
        print("Failed to fetch any data. No updates made.")
        exit(1)


if __name__ == '__main__':
    main()
