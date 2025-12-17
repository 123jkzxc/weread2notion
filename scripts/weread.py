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
        print(f"返回数据：{data}")  # 调试输出
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


if __name__ == "__main__":
    print("🚀 weread2notion 启动中…")

    # 初始化会话
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://weread.qq.com/"
    })

    # 加载环境变量
    cookie_string = os.getenv("WEREAD_COOKIE")
    if not cookie_string:
        raise RuntimeError("未检测到 WEREAD_COOKIE")
    session.cookies = parse_cookie_string(cookie_string)

    notion_token = os.getenv("NOTION_TOKEN")
    database_id = os.getenv("NOTION_DATABASE_ID")
    if not notion_token or not database_id:
        raise RuntimeError("未检测到 Notion 配置")
    client = Client(auth=notion_token)
    print("✅ 环境初始化完成")

    # 主逻辑
    try:
        books = get_notebooklist()
        if not books:
            print("⚠️ 无法获取书籍列表，请检查登录状态或网络连接")
            exit()
        for book in books:
            book_id = book.get("bookId")
            bookmarks = get_bookmark_list(book_id)
            if not bookmarks:
                print(f"⚠️ 无法同步划线，书 ID：{book_id}")
            else:
                print(f"✅ 同步完成，书 ID：{book_id}")
    except Exception as e:
        print(f"❌ 程序运行出错：{e}")
