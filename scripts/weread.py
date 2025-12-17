import argparse
import json
import logging
import os
import re
import time
from notion_client import Client
import requests
from requests.utils import cookiejar_from_dict
from http.cookies import SimpleCookie
from datetime import datetime
import hashlib
from dotenv import load_dotenv
from retrying import retry
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

load_dotenv()
WEREAD_URL = "https://weread.qq.com/"
WEREAD_NOTEBOOKS_URL = "https://weread.qq.com/api/user/notebook"
WEREAD_BOOKMARKLIST_URL = "https://weread.qq.com/web/book/bookmarklist"
WEREAD_CHAPTER_INFO = "https://weread.qq.com/web/book/chapterInfos"
WEREAD_READ_INFO_URL = "https://weread.qq.com/web/book/readinfo"
WEREAD_REVIEW_LIST_URL = "https://weread.qq.com/web/review/list"
WEREAD_BOOK_INFO = "https://weread.qq.com/web/book/info"


def parse_cookie_string(cookie_string):
    cookie = SimpleCookie()
    cookie.load(cookie_string)
    cookies_dict = {}
    cookiejar = None
    for key, morsel in cookie.items():
        cookies_dict[key] = morsel.value
        cookiejar = cookiejar_from_dict(cookies_dict, cookiejar=None, overwrite=True)
    return cookiejar


def refresh_token(exception=None):
    print("⚠️ 微信读书登录态可能失效，尝试刷新 Cookie / Session …")
    try:
        session.get(WEREAD_URL, timeout=10)
        time.sleep(5)
        return True
    except requests.exceptions.RequestException as e:
        print(f"❌ 网络请求异常: {e}")
        return False
    except Exception as e:
        print(f"❌ 未知错误: {e}")
        return False


@retry(stop_max_attempt_number=3, wait_fixed=5000, retry_on_exception=refresh_token)
def get_bookmark_list(bookId):
    """获取我的划线"""
    if not bookId:
        raise ValueError("Invalid bookId provided")
    session.get(WEREAD_URL)
    params = dict(bookId=bookId)
    r = session.get(WEREAD_BOOKMARKLIST_URL, params=params)

    if r.ok:
        data = r.json()
        if data.get("errCode") == -2012:
            print("🔁 登录超时，刷新 session 后重试本书：", bookId)
            refresh_token()
            time.sleep(5)
            return None
        updated = data.get("updated")
        updated = sorted(
            updated,
            key=lambda x: (x.get("chapterUid", 1), int(x.get("range").split("-")[0])),
        )
        return updated
    return None


@retry(stop_max_attempt_number=3, wait_fixed=5000, retry_on_exception=refresh_token)
def get_read_info(bookId):
    if not bookId:
        raise ValueError("Invalid bookId provided")
    session.get(WEREAD_URL)
    params = dict(bookId=bookId, readingDetail=1, readingBookIndex=1, finishedDate=1)
    r = session.get(WEREAD_READ_INFO_URL, params=params)
    if r.ok:
        return r.json()
    return None


@retry(stop_max_attempt_number=3, wait_fixed=5000, retry_on_exception=refresh_token)
def get_bookinfo(bookId):
    """获取书的详情"""
    if not bookId:
        raise ValueError("Invalid bookId provided")
    session.get(WEREAD_URL)
    params = dict(bookId=bookId)
    r = session.get(WEREAD_BOOK_INFO, params=params)
    if r.ok:
        data = r.json()
        isbn = data.get("isbn", "")
        newRating = data.get("newRating", 0) / 1000
        return isbn, newRating
    else:
        print(f"get {bookId} book info failed")
        return "", 0


@retry(stop_max_attempt_number=3, wait_fixed=5000, retry_on_exception=refresh_token)
def get_review_list(bookId):
    """获取书评和笔记总结"""
    session.get(WEREAD_URL)
    params = dict(bookId=bookId)
    r = session.get(WEREAD_REVIEW_LIST_URL, params=params)

    try:
        data = r.json()
    except Exception as e:
        print("❌ 解析书评返回失败：", e)
        return None, None

    if data.get("errCode") == -2012:
        print("🔁 登录超时，刷新 session，跳过本书书评：", bookId)
        refresh_token()
        time.sleep(5)
        return None, None

    reviews = data.get("reviews")
    if not reviews:
        return None, None

    try:
        summary = list(
            filter(lambda x: x.get("review", {}).get("type") == 4, reviews)
        )
        reviews = list(
            filter(lambda x: x.get("review", {}).get("type") != 4, reviews)
        )
    except Exception as e:
        print("⚠️ 处理书评失败，跳过本书：", bookId, e)
        return None, None

    return summary, reviews


def check(bookId):
    """检查是否已经插入过 如果已经插入了就删除"""
    filter = {"property": "BookId", "rich_text": {"equals": bookId}}
    response = client.databases.query(database_id=database_id, filter=filter)
    for result in response["results"]:
        try:
            client.blocks.delete(block_id=result["id"])
        except Exception as e:
            print(f"删除块时出错: {e}")


@retry(stop_max_attempt_number=3, wait_fixed=5000, retry_on_exception=refresh_token)
def get_chapter_info(bookId):
    """获取章节信息"""
    session.get(WEREAD_URL)
    body = {"bookIds": [bookId], "synckeys": [0], "teenmode": 0}
    r = session.post(WEREAD_CHAPTER_INFO, json=body)
    if r.ok and "data" in r.json() and len(r.json()["data"]) == 1:
        update = r.json()["data"][0].get("updated")
        if update:
            return {item["chapterUid"]: item for item in update}
    return None


def insert_to_notion(bookName, bookId, cover, sort, author, isbn, rating, categories):
    """插入到Notion"""
    if not cover or not cover.startswith("http"):
        cover = "https://www.notion.so/icons/book_gray.svg"
    parent = {"database_id": database_id, "type": "database_id"}
    properties = {
        "BookName": get_title(bookName),
        "BookId": get_rich_text(bookId),
        "ISBN": get_rich_text(isbn),
        "URL": get_url(
            f"https://weread.qq.com/web/reader/{calculate_book_str_id(bookId)}"
        ),
        "Author": get_rich_text(author),
        "Sort": get_number(sort),
        "Rating": get_number(rating),
        "Cover": get_file(cover),
    }
    if categories is not None:
        properties["Categories"] = get_multi_select(categories)
    read_info = get_read_info(bookId=bookId)
    if read_info is not None:
        markedStatus = read_info.get("markedStatus", 0)
        readingTime = read_info.get("readingTime", 0)
        readingProgress = read_info.get("readingProgress", 0)
        format_time = ""
        hour = readingTime // 3600
        if hour > 0:
            format_time += f"{hour}时"
        minutes = readingTime % 3600 // 60
        if minutes > 0:
            format_time += f"{minutes}分"
        properties["Status"] = get_select("读完" if markedStatus == 4 else "在读")
        properties["ReadingTime"] = get_rich_text(format_time)
        properties["Progress"] = get_number(readingProgress)
        if "finishedDate" in read_info:
            properties["Date"] = get_date(
                datetime.utcfromtimestamp(read_info.get("finishedDate")).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            )
    try:
        icon = get_icon(cover)
        response = client.pages.create(
            parent=parent, icon=icon, cover=icon, properties=properties
        )
        return response["id"]
    except Exception as e:
        print(f"插入到 Notion 时出错: {e}")
        return None


# Main logic remains unchanged...
         if __name__ == "__main__":
    print("🚀 weread2notion 启动中…")

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://weread.qq.com/",
        }
    )

    cookie_string = os.getenv("WEREAD_COOKIE")
    if not cookie_string:
        raise RuntimeError("❌ 未检测到 WEREAD_COOKIE")

    session.cookies = parse_cookie_string(cookie_string)

    notion_token = os.getenv("NOTION_TOKEN")
    database_id = os.getenv("NOTION_DATABASE_ID")

    if not notion_token or not database_id:
        raise RuntimeError("❌ 未检测到 Notion 配置")

    client = Client(auth=notion_token)

    print("✅ 环境初始化完成")
