#!/usr/bin/env python3
"""
Update README.md with latest Bilibili and CSDN statistics
"""

import json
from pathlib import Path


def format_number(num):
    """格式化数字，添加千位分隔符"""
    if num >= 10000:
        return f"{num/10000:.1f}万"
    return f"{num:,}"


def update_readme():
    """更新README.md中的B站和CSDN数据"""
    # 读取stats数据
    bilibili_stats_file = Path(__file__).parent.parent / 'data' / 'bilibili-stats.json'
    csdn_stats_file = Path(__file__).parent.parent / 'data' / 'csdn-stats.json'
    readme_file = Path(__file__).parent.parent / 'README.md'

    # 读取README内容
    with open(readme_file, 'r', encoding='utf-8') as f:
        readme_content = f.read()

    # 更新Bilibili数据
    if bilibili_stats_file.exists():
        with open(bilibili_stats_file, 'r', encoding='utf-8') as f:
            bilibili_stats = json.load(f)

        follower = bilibili_stats.get('follower', 0)
        views = bilibili_stats.get('views', 0)
        likes = bilibili_stats.get('likes', 0)

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

        print(f"Bilibili stats:")
        print(f"  Follower: {format_number(follower)}")
        print(f"  Views: {format_number(views)}")
        print(f"  Likes: {format_number(likes)}")
    else:
        print("Bilibili stats file not found!")

    # 更新CSDN数据
    if csdn_stats_file.exists():
        with open(csdn_stats_file, 'r', encoding='utf-8') as f:
            csdn_stats = json.load(f)

        fans = csdn_stats.get('fans', 0)
        csdn_likes = csdn_stats.get('likes', 0)
        collect = csdn_stats.get('collect', 0)
        original = csdn_stats.get('original', 0)

        readme_content = readme_content.replace(
            '<!--CSDN_FANS-->',
            format_number(fans)
        )
        readme_content = readme_content.replace(
            '<!--CSDN_LIKES-->',
            format_number(csdn_likes)
        )
        readme_content = readme_content.replace(
            '<!--CSDN_COLLECT-->',
            format_number(collect)
        )
        readme_content = readme_content.replace(
            '<!--CSDN_ORIGINAL-->',
            format_number(original)
        )

        print(f"\nCSDN stats:")
        print(f"  Fans: {format_number(fans)}")
        print(f"  Likes: {format_number(csdn_likes)}")
        print(f"  Collect: {format_number(collect)}")
        print(f"  Original: {format_number(original)}")
    else:
        print("CSDN stats file not found!")

    # 写回README
    with open(readme_file, 'w', encoding='utf-8') as f:
        f.write(readme_content)

    print(f"\nREADME.md updated successfully!")
    return True


if __name__ == '__main__':
    if not update_readme():
        exit(1)
