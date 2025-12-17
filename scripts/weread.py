if __name__ == "__main__":
    print("🚀 weread2notion 启动中…")

    # 配置环境变量检查
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://weread.qq.com/"
    })

    cookie_string = os.getenv("WEREAD_COOKIE")
    if not cookie_string:
        raise RuntimeError("未检测到 WEREAD_COOKIE")

    # 解析 Cookie，初始化 session
    session.cookies = parse_cookie_string(cookie_string)

    notion_token = os.getenv("NOTION_TOKEN")
    database_id = os.getenv("NOTION_DATABASE_ID")
    if not notion_token or not database_id:
        raise RuntimeError("未检测到 Notion 配置")

    client = Client(auth=notion_token)
    print("✅ Notion 已成功初始化")
    
    # 获取书单逻辑
    books = get_notebooklist()
    if not books:
        print("⚠️ 无法获取书籍列表，请检查登录状态或网络连接")
        exit()
    
    latest_sort = get_sort()
    for book in books:
        book_id = book.get("bookId")
        book_sort = book.get("sort", 0)
        if book_sort <= latest_sort:
            continue
        
        # 获取并插入书籍相关信息到 Notion
        bookmarks = get_bookmark_list(book_id)
        summary, reviews = get_review_list(book_id)
        chapter_info = get_chapter_info(book_id)
        book_name = book.get("title")
        cover = book.get("cover")
        author = ", ".join(book.get("author", []))
        isbn, rating = get_bookinfo(book_id)

        notion_page_id = insert_to_notion(
            book_name, book_id, cover, book_sort, author, isbn, rating, None
        )
        children, grandchild = get_children(chapter_info, summary, bookmarks)
        
        if notion_page_id and children:
            result = add_children(notion_page_id, children)
            if result and grandchild:
                add_grandchild(grandchild, result)

        print(f"✅ 更新完成：《{book_name}》")
    
    print("🚀 同步任务完成")
