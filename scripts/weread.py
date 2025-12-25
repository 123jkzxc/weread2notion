import argparse
import json
import logging
import os
import re
import time
from datetime import datetime
from http.cookies import SimpleCookie

import requests
from dotenv import load_dotenv
from notion_client import Client
from retrying import retry  # 确保导入正确

from utils import (
    get_callout,
    get_date,
    get_file,
    get_heading,
    get_icon,
    get_multi_select,
    get_number,
    get_quote,
    get_rich_text,
    get_select,
    get_table_of_contents,
    get_title,
    get_url,
)

# 加载环境变量
load_dotenv()
WEREAD_URL = "https://weread.qq.com/"
WEREAD_NOTEBOOKS_URL = "https://weread.qq.com/api/user/notebook"
WEREAD_BOOKMARKLIST_URL = "https://weread.qq.com/web/book/bookmarklist"
WEREAD_CHAPTER_INFO = "https://weread.qq.com/web/book/chapterInfos"
WEREAD_READ_INFO_URL = "https://weread.qq.com/web/book/readinfo"
WEREAD_REVIEW_LIST_URL = "https://weread.qq.com/web/review/list"
WEREAD_BOOK_INFO = "https://weread.qq.com/web/book/info"


def parse_cookie_string(cookie_string):
    """解析 cookie 字符串"""
    cookie = SimpleCookie()
    cookie.load(cookie_string)
    cookies_dict = {}
    cookiejar = None
    for key, morsel in cookie.items():
        cookies_dict[key] = morsel.value
    return requests.utils.cookiejar_from_dict(cookies_dict)


def refresh_token(exception):
    """尝试刷新微信读书的登录会话"""
    global session
    print("⚠️ 微信读书登录态可能失效，尝试刷新 Cookie / Session …")
    try:
        session.get(WEREAD_URL, timeout=10)
        time.sleep(5)
        return True
    except requests.exceptions. RequestException as e:
        print(f"❌ 网络请求异常: {e}")
        return False
    except Exception as e:
        print(f"❌ 未知错误: {e}")
        return False


@retry(stop_max_attempt_number=3, wait_fixed=5000, retry_on_exception=refresh_token)
def get_bookmark_list(bookId):
    """获取我的划线"""
    session.get(WEREAD_URL)
    params = dict(bookId=bookId)
    r = session.get(WEREAD_BOOKMARKLIST_URL, params=params)
    if r.ok:
        data = r.json()
        print(f"返回书籍划线数据: {data}")  # 调试输出
        updated = data.get("updated")
        if not updated:
            print(f"⚠️ 无法获取划线内容，返回数据为空。书 ID：{bookId}")
            return None
        updated = sorted(
            updated,
            key=lambda x: (x.get("chapterUid", 1), int(x.get("range").split("-")[0])),
        )
        return updated
    print(f"❌ 请求失败，HTTP 状态码：{r.status_code}, 书 ID：{bookId}")
    return None


@retry(stop_max_attempt_number=3, wait_fixed=5000, retry_on_exception=refresh_token)
def get_notebooklist():
    """获取书籍列表"""
    session.get(WEREAD_URL)
    r = session.get(WEREAD_NOTEBOOKS_URL)
    if r.ok:
        books = r.json().get("books")
        books. sort(key=lambda x: x["sort"])
        return books
    print("❌ 无法获取书籍列表，返回:", r.text)
    return None


def sync_bookmarks_to_notion(client, database_id, book, bookmarks):
    """将划线同步到 Notion 数据库"""
    try:
        book_title = book.get("title", "Unknown")
        book_id = book.get("bookId")
        book_author = book.get("author", "")
        
        # 构建每条划线的内容
        children = []
        for bookmark in bookmarks:
            text = bookmark.get("text", "")
            chapter_uid = bookmark.get("chapterUid", "")
            
            if text: 
                # 添加划线内容作为段落
                children.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text":  {
                                    "content": text,
                                    "link": None
                                }
                            }
                        ]
                    }
                })
        
        # 创建 Notion 页面
        page_data = {
            "parent": {"database_id": database_id},
            "properties": {
                "title": [
                    {
                        "type": "text",
                        "text": {
                            "content": book_title
                        }
                    }
                ]
            },
            "children": children if children else [
                {
                    "object":  "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {
                                    "content": "暂无划线"
                                }
                            }
                        ]
                    }
                }
            ]
        }
        
        response = client.pages.create(**page_data)
        print(f"✅ 书籍 '{book_title}' 的 {len(bookmarks)} 条划线已同步到 Notion")
        return True
    except Exception as e:
        print(f"❌ 同步失败: {e}")
        return False


if __name__ == "__main__": 
    print("🚀 weread2notion 启动中…")

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://weread.qq.com/",
        }
    )

    # 检查并加载环境变量
    cookie_string = os.getenv("WEREAD_COOKIE")
    if not cookie_string:
        raise RuntimeError("未检测到 WEREAD_COOKIE")
    session.cookies = parse_cookie_string(cookie_string)

    notion_token = os.getenv("NOTION_TOKEN")
    database_id = os.getenv("NOTION_DATABASE_ID")
    if not notion_token or not database_id:
        raise RuntimeError("未检测到 Notion 配置")
    
    client = Client(auth=notion_token)
    print("✅ Notion 配置初始化完成")
    
    # 开始拉取书籍信息
    books = get_notebooklist()
    if not books:
        print("⚠️ 无法获取书籍列表，请检查登录状态或数据为空")
        exit()
    
    print("📚 开始同步书籍笔记与划线")
    for book in books:
        book_id = book.get("bookId")
        print(f"📖 当前处理书籍:  {book. get('title')} (ID: {book_id})")
        bookmarks = get_bookmark_list(book_id)
        if bookmarks is None:
            print(f"⚠️ 跳过书籍 ID:  {book_id}")
        else:
            # 同步到 Notion
            sync_bookmarks_to_notion(client, database_id, book, bookmarks)
            time.sleep(1)  # 避免 API 限流

    print("📂 所有任务处理完成")
