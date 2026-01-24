#!/usr/bin/env python3
"""
Update README.md with latest Bilibili statistics
"""

import json
from pathlib import Path


def format_number(num):
    """格式化数字，添加千位分隔符"""
    if num >= 10000:
        return f"{num/10000:.1f}万"
    return f"{num:,}"


def update_readme():
    """更新README.md中的B站数据"""
    # 读取stats数据
    stats_file = Path(__file__).parent.parent / 'data' / 'bilibili-stats.json'
    readme_file = Path(__file__).parent.parent / 'README.md'

    if not stats_file.exists():
        print("Stats file not found!")
        return False

    with open(stats_file, 'r', encoding='utf-8') as f:
        stats = json.load(f)

    # 读取README内容
    with open(readme_file, 'r', encoding='utf-8') as f:
        readme_content = f.read()

    # 替换占位符
    follower = stats.get('follower', 0)
    views = stats.get('views', 0)
    likes = stats.get('likes', 0)

    readme_content = readme_content.replace(
        '<!--BILIBILI_FOLLOWER-->',
        format_number(follower)
    )
    readme_content = readme_content.replace(
        '<!--BILIBILI_VIEWS-->',
        format_number(views)
    )
    readme_content = readme_content.replace(
        '<!--BILIBILI_LIKES-->',
        format_number(likes)
    )

    # 写回README
    with open(readme_file, 'w', encoding='utf-8') as f:
        f.write(readme_content)

    print(f"README.md updated successfully!")
    print(f"Follower: {format_number(follower)}")
    print(f"Views: {format_number(views)}")
    print(f"Likes: {format_number(likes)}")

    return True


if __name__ == '__main__':
    if not update_readme():
        exit(1)
