import requests
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
from urllib.parse import urljoin
from collections import deque
import re

BASE_URL = "https://github.com/eea/copernicus_quality_tools/wiki"
DOMAIN_PREFIX = "/eea/copernicus_quality_tools/wiki"

def is_valid_wiki_url(url: str) -> bool:
    """
    Accept only URLs of the form:
      /eea/copernicus_quality_tools/wiki/Page-Name
    Rejects:
      /eea/copernicus_quality_tools/wiki/Page/with/extra
    """
    # Strip the domain
    if not url.startswith("https://github.com"):
        return False
    path = url.replace("https://github.com", "")
    return re.fullmatch(rf"{DOMAIN_PREFIX}(/[\w\-%()]+)?", path) is not None

def get_wiki_links(page_url):
    """Extract all valid wiki links from a single page."""
    try:
        resp = requests.get(page_url)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"❌ Error fetching {page_url}: {e}")
        return []
    
    soup = BeautifulSoup(resp.text, "html.parser")
    links = []
    for a in soup.select(f"a[href^='{DOMAIN_PREFIX}']"):
        href = a["href"]
        url = urljoin("https://github.com", href)
        if is_valid_wiki_url(url):
            links.append(url)
    return links

def crawl_wiki(base_url):
    """Breadth-first crawl of all wiki pages."""
    visited = set()
    queue = deque([base_url])

    while queue:
        url = queue.popleft()
        if url in visited:
            continue
        visited.add(url)

        print(f"🔎 Crawling: {url}")
        for link in get_wiki_links(url):
            if link not in visited:
                queue.append(link)

    return sorted(visited)

def indent(elem, level=0):
    """Pretty-print XML with newlines and indentation."""
    i = "\n" + level*"  "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "  "
        for child in elem:
            indent(child, level+1)
        if not child.tail or not child.tail.strip():
            child.tail = i
    if level and (not elem.tail or not elem.tail.strip()):
        elem.tail = i

def generate_sitemap(urls):
    urlset = ET.Element("urlset", xmlns="http://www.sitemaps.org/schemas/sitemap/0.9")
    for url in urls:
        url_el = ET.SubElement(urlset, "url")
        loc = ET.SubElement(url_el, "loc")
        loc.text = url
    indent(urlset)
    return ET.ElementTree(urlset)

if __name__ == "__main__":
    wiki_links = crawl_wiki(BASE_URL)
    print(f"\n✅ Found {len(wiki_links)} clean wiki pages in total")

    sitemap = generate_sitemap(wiki_links)
    sitemap.write("sitemap.xml", encoding="utf-8", xml_declaration=True)
    print("📄 sitemap.xml generated.")
