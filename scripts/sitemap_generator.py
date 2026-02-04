import os
import requests
from bs4 import BeautifulSoup
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom

def generate_github_wiki_sitemap(wiki_url, base_path):
    print(f"Fetching {wiki_url}...")
    try:
        response = requests.get(wiki_url)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Error: {e}")
        return

    soup = BeautifulSoup(response.text, 'html.parser')
    unique_urls = set()
    
    # Define the strings we want to exclude
    exclusions = ('_delete', '_history')
    
    for link in soup.find_all('a', href=True):
        href = link['href']
        
        if href.startswith(base_path):
            # 1. Strip anchors/fragments
            clean_url = href.split('#')[0]
            
            # 2. Check if the URL ends with our excluded terms
            if not clean_url.endswith(exclusions):
                full_url = f"https://github.com{clean_url}"
                unique_urls.add(full_url)

    # Create XML structure
    urlset = Element('urlset')
    urlset.set('xmlns', 'http://www.sitemaps.org/schemas/sitemap/0.9')

    for url in sorted(list(unique_urls)):
        url_node = SubElement(urlset, 'url')
        loc_node = SubElement(url_node, 'loc')
        loc_node.text = url

    # Format and Save
    xml_str = minidom.parseString(tostring(urlset)).toprettyxml(indent="  ")
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(current_dir)
    xml_file_path = os.path.join(parent_dir, "sitemap.xml")
    with open(xml_file_path, "w", encoding="utf-8") as f:
        f.write(xml_str)
    
    print(f"Success! Found {len(unique_urls)} valid unique URLs.")
    print("Excluded all URLs ending in _delete or _history.")

# Parameters
WIKI_HOME = "https://github.com/eea/copernicus_quality_tools/wiki"
PATH_FILTER = "/eea/copernicus_quality_tools/wiki"

if __name__ == "__main__":
    generate_github_wiki_sitemap(WIKI_HOME, PATH_FILTER)