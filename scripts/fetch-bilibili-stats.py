#!/usr/bin/env python3
"""
Fetch Bilibili statistics and update data/bilibili-stats.json
"""

import json
import os
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
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-site',
}

# 从环境变量获取 Cookie（用于需要登录态的 API）
BILI_SESSDATA = os.environ.get('BILI_SESSDATA', '')
BILI_BILI_JCT = os.environ.get('BILI_BILI_JCT', '')


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
    """获取播放数和获赞数（需要登录态）"""
    try:
        # 构建 Cookie 字符串
        cookies = {}
        if BILI_SESSDATA:
            cookies['SESSDATA'] = BILI_SESSDATA
        if BILI_BILI_JCT:
            cookies['bili_jct'] = BILI_BILI_JCT

        response = requests.get(STATS_API, headers=HEADERS, cookies=cookies, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data.get('code') == 0:
            stats_data = data.get('data', {})
            views = stats_data.get('archive', {}).get('view', 0)
            likes = stats_data.get('likes', 0)
            return views, likes
        else:
            error_msg = data.get('message', 'Unknown error')
            print(f"Error fetching views and likes: {error_msg}")
            if data.get('code') == -101:
                print("Tip: This API requires login. Please set BILI_SESSDATA and BILI_BILI_JCT environment variables.")
            return None, None
    except Exception as e:
        print(f"Exception when fetching views and likes: {e}")
        import traceback
        traceback.print_exc()
        return None, None


def update_stats_file(follower, views, likes):
    """更新stats JSON文件（只在值有效且>0时更新）"""
    stats_file = Path(__file__).parent.parent / 'data' / 'bilibili-stats.json'

    # Read existing data
    if stats_file.exists():
        with open(stats_file, 'r', encoding='utf-8') as f:
            existing_data = json.load(f)
    else:
        existing_data = {}

    # Update with new values (only if valid and > 0)
    if follower is not None and follower > 0:
        existing_data['follower'] = follower
        print(f"✓ Updated follower: {follower}")
    elif follower is not None and follower <= 0:
        print(f"⚠ Skipped invalid follower value: {follower}, keeping existing: {existing_data.get('follower', 'N/A')}")

    if views is not None and views > 0:
        existing_data['views'] = views
        print(f"✓ Updated views: {views}")
    elif views is not None and views <= 0:
        print(f"⚠ Skipped invalid views value: {views}, keeping existing: {existing_data.get('views', 'N/A')}")

    if likes is not None and likes > 0:
        existing_data['likes'] = likes
        print(f"✓ Updated likes: {likes}")
    elif likes is not None and likes <= 0:
        print(f"⚠ Skipped invalid likes value: {likes}, keeping existing: {existing_data.get('likes', 'N/A')}")

    existing_data['last_updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Write back to file
    stats_file.parent.mkdir(parents=True, exist_ok=True)
    with open(stats_file, 'w', encoding='utf-8') as f:
        json.dump(existing_data, f, ensure_ascii=False, indent=2)

    print(f"\nStats updated successfully!")
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
