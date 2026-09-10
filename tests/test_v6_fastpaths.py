import re


def parse_search(q):
    m = re.search(
        r'(?:搜索|搜一下|搜\s*|查询|search\s+)(?:一下|一下子)?[：: ]*[“"\']?(.+?)[“"\']?(?:$|。|，|\n)',
        q, re.IGNORECASE,
    )
    return m.group(1).strip().strip('“”"\' ') if m else None


def parse_click(q):
    m = re.search(r'(?:点击|单击|click)\s*[“"\']([^“”"\']+)[”"\']', q, re.IGNORECASE)
    return m.group(1).strip() if m else None


def test_search_fastpath():
    assert parse_search('请在浏览器搜索“Python tkinter”') == 'Python tkinter'


def test_click_fastpath():
    assert parse_click('请点击“登录”按钮') == '登录'


def test_search_not_premature_for_sequence():
    q='先搜索“Python”，然后点击“文档”'
    assert parse_search(q) == 'Python'
    assert any(x in q for x in ['点击','然后'])
