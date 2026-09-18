import os
import time
from DrissionPage import ChromiumOptions, Chromium
import markdownify

def sanitize_filename(filename):
    import re
    return re.sub(r'[\\/*?:"<>|]', "", filename).strip()

def main():
    options = ChromiumOptions()
    options.set_browser_path("/usr/bin/google-chrome")
    options.set_user_data_path("/home/ubuntu/google_flow_mcp/chrome_data")
    options.set_local_port(9222)
    options.headless(True)
    options.set_argument("--remote-debugging-address=0.0.0.0")
    options.set_argument("--remote-allow-origins=*")
    options.set_argument("--no-sandbox")

    browser = Chromium(addr_or_opts=options)
    tab = browser.get_tab()

    start_url = "https://www.drissionpage.cn/browser_control/get_elements/intro"
    tab.get(start_url)
    
    # Wait for sidebar to load
    tab.wait.ele_displayed('c:theme-doc-sidebar-menu')
    time.sleep(1)
    
    links = tab.eles('t:a')
    pages_to_scrape = []
    
    seen_urls = set()
    idx = 1
    for link in links:
        href = link.link
        if href and "/get_elements/" in href and href not in seen_urls:
            # Docusaurus sidebars can have multiple duplicate links (e.g., mobile menu vs desktop menu),
            # but setting `seen_urls` filters them.
            seen_urls.add(href)
            text = link.text.strip()
            if not text:
                continue
            title = sanitize_filename(f"{idx:02d}_{text}")
            pages_to_scrape.append({
                "title": title,
                "url": href
            })
            idx += 1

    print(f"Found {len(pages_to_scrape)} pages to scrape for 查找元素.")
    
    base_dir = "/home/ubuntu/google_flow_mcp/docs/drissionpage/01_🚀 控制浏览器/09_🔎 查找元素"
    os.makedirs(base_dir, exist_ok=True)
    
    for page_info in pages_to_scrape:
        file_path = os.path.join(base_dir, f"{page_info['title']}.md")
        print(f"Scraping {page_info['url']} -> {file_path}")
        
        tab.get(page_info['url'])
        try:
            article = tab.wait.ele_displayed('t:article', timeout=10)
            if article:
                html_content = article.html
                md_content = markdownify.markdownify(
                    html_content, 
                    heading_style="ATX", 
                    strip=['script', 'style', 'button']
                )
                
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(md_content)
                print(f"Saved {file_path}")
            else:
                print(f"Failed to find article for {page_info['url']}")
        except Exception as e:
            print(f"Error scraping {page_info['url']}: {e}")
            
        time.sleep(1)

    browser.quit()

if __name__ == "__main__":
    main()
