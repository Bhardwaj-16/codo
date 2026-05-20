from ddgs import DDGS
import trafilatura
import requests
from bs4 import BeautifulSoup


def search(query, max_results=5):
    results = DDGS().text(
        query,
        max_results=max_results
    )

    clean_results = []

    for r in results:
        clean_results.append({
            "title": r.get("title"),
            "url": r.get("href"),
            "snippet": r.get("body")
        })

    return clean_results


def extract_content(url):
    try:
        downloaded = trafilatura.fetch_url(url)

        if not downloaded:
            return None

        text = trafilatura.extract(
            downloaded,
            include_links=False,
            include_images=False
        )

        return text

    except Exception as e:
        print(f"Extraction failed: {e}")
        return None


def extract_links(url):
    try:
        response = requests.get(
            url,
            timeout=10,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        soup = BeautifulSoup(response.text, "html.parser")

        links = []

        for a in soup.find_all("a", href=True):
            href = a["href"]

            if href.startswith("http"):
                links.append(href)

        return list(set(links))

    except Exception as e:
        print(f"Link extraction failed: {e}")
        return []


def search_and_extract(query):
    print(f"\nSearching for: {query}\n")

    results = search(query)

    all_data = []

    for idx, result in enumerate(results, start=1):

        print("=" * 80)
        print(f"[{idx}] {result['title']}")
        print(result["url"])

        content = extract_content(result["url"])

        if not content:
            print("No extractable content\n")
            continue

        print("\nCONTENT PREVIEW:\n")
        print(content[:1500])

        links = extract_links(result["url"])

        print(f"\nFound {len(links)} links")

        all_data.append({
            "title": result["title"],
            "url": result["url"],
            "content": content,
            "links": links
        })

    return all_data

# print(search_and_extract((""))