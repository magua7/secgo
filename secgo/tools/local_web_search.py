"""Web 搜索工具：Bing 结果解析（httpx）。"""

import html as html_lib
import re
from typing import Any, Dict
from urllib.parse import unquote

import httpx

MAX_RESULTS = 5
SEARCH_TIMEOUT_S = 10

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]*>", "", text)
    return html_lib.unescape(text).strip()


def _decode_bing_url(url: str) -> str:
    match = re.search(r"[?&]redirect=([^&]+)", url)
    if match:
        try:
            return unquote(match.group(1))
        except Exception:
            return url
    return url


def _parse_bing_results(html_text: str) -> list:
    results = []
    blocks = html_text.split('class="b_algo"')
    for block in blocks[1 : MAX_RESULTS + 1]:
        title_match = re.search(
            r'<h2[^>]*>.*?<a[^>]+href="([^"]*)"[^>]*>(.*?)</a>', block, re.DOTALL
        )
        if not title_match:
            continue
        url = _decode_bing_url(title_match.group(1))
        title = _strip_html(title_match.group(2))
        snippet_match = re.search(
            r'class="b_caption"[^>]*>.*?<p[^>]*>(.*?)</p>', block, re.DOTALL
        ) or re.search(r'class="b_lineclamp[^"]*"[^>]*>(.*?)</(?:p|div)>', block, re.DOTALL)
        snippet = _strip_html(snippet_match.group(1)) if snippet_match else ""
        if title:
            results.append({"title": title, "snippet": snippet, "url": url})
    return results


async def execute_web_search(query: str) -> Dict[str, Any]:
    if not query or not query.strip():
        return {"success": False, "error": "Empty search query"}

    search_url = f"https://cn.bing.com/search?q={httpx.QueryParams({'q': query})['q']}&count={MAX_RESULTS}"
    try:
        async with httpx.AsyncClient(timeout=SEARCH_TIMEOUT_S, headers=_HEADERS) as client:
            response = await client.get(search_url)
            html_text = response.text
    except httpx.TimeoutException:
        return {"success": False, "error": f"Search timed out after {SEARCH_TIMEOUT_S}s"}
    except httpx.HTTPError as err:
        return {"success": False, "error": f"Web search failed: {err}"}

    results = _parse_bing_results(html_text)
    if not results:
        return {"success": True, "output": "No search results found."}

    formatted = "\n\n".join(
        f"{i + 1}. {r['title']}\n   {r['snippet']}\n   URL: {r['url']}"
        for i, r in enumerate(results)
    )
    return {"success": True, "output": f'Search results for "{query}":\n\n{formatted}'}
