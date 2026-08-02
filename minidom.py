#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
極簡 HTML → 樹狀結構解析器（只用標準函式庫，零安裝）

之所以不用 BeautifulSoup：整個專案要能在 GitHub Actions 的乾淨環境
直接 `python3 pipeline.py` 跑起來，不想為了三支爬蟲多一個相依套件。

用法：
    root = parse(html)
    for card in root.find_all(cls="item-static"):
        title = card.first_text(cls="card-text-name")
"""
from html.parser import HTMLParser

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr"}


class Node:
    __slots__ = ("tag", "attrs", "children", "parent", "_text")

    def __init__(self, tag, attrs=None, parent=None):
        self.tag = tag
        self.attrs = attrs or {}
        self.children = []
        self.parent = parent
        self._text = []

    # ---- 屬性 ----
    @property
    def classes(self):
        return (self.attrs.get("class") or "").split()

    def get(self, name, default=None):
        return self.attrs.get(name, default)

    # ---- 文字 ----
    @property
    def text(self):
        """遞迴取出所有文字，空白正規化。"""
        parts = list(self._text)
        for c in self.children:
            t = c.text
            if t:
                parts.append(t)
        return " ".join(" ".join(parts).split())

    # ---- 查詢 ----
    def find_all(self, tag=None, cls=None):
        out = []
        for c in self.children:
            if (tag is None or c.tag == tag) and (cls is None or cls in c.classes):
                out.append(c)
            out.extend(c.find_all(tag, cls))
        return out

    def find(self, tag=None, cls=None):
        r = self.find_all(tag, cls)
        return r[0] if r else None

    def first_text(self, tag=None, cls=None, default=""):
        n = self.find(tag, cls)
        return n.text if n else default

    def __repr__(self):
        return f"<{self.tag} class={' '.join(self.classes)!r}>"


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root")
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs), self.cur)
        self.cur.children.append(node)
        if tag not in VOID:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(Node(tag, dict(attrs), self.cur))

    def handle_endtag(self, tag):
        node = self.cur
        while node is not self.root:
            if node.tag == tag:
                self.cur = node.parent
                return
            node = node.parent
        # 找不到對應開標籤就忽略（容錯）

    def handle_data(self, data):
        if data.strip():
            self.cur._text.append(data)


def parse(html: str) -> Node:
    b = _Builder()
    b.feed(html)
    return b.root
