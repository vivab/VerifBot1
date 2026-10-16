"""Consistent 5-item lists across catalogs, orders and chats."""
PAGE_SIZE = 5

def page_slice(items, page: int):
    page = max(0, min(int(page), 10000))
    start = page * PAGE_SIZE
    return items[start:start + PAGE_SIZE], page, page > 0, len(items) > start + PAGE_SIZE

def add_page_arrows(builder, page, previous: bool, following: bool, callback_prefix: str):
    if previous:
        builder.button(text="⬅️", callback_data=f"{callback_prefix}:{page - 1}")
    if following:
        builder.button(text="➡️", callback_data=f"{callback_prefix}:{page + 1}")
