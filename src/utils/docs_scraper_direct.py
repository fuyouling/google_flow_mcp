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

    pages = {
        "03_🧰 进阶使用": [
            "https://www.drissionpage.cn/advance/ini",
            "https://www.drissionpage.cn/advance/settings",
            "https://www.drissionpage.cn/advance/commands",
            "https://www.drissionpage.cn/advance/errors",
            "https://www.drissionpage.cn/advance/accelerate",
            "https://www.drissionpage.cn/advance/packaging",
            "https://www.drissionpage.cn/advance/tools",
            "https://www.drissionpage.cn/advance/docking"
        ],
        "04_⬇️ 下载工具与相关": [
            "https://www.drissionpage.cn/download/intro",
            "https://www.drissionpage.cn/download/DownloadKit",
            "https://www.drissionpage.cn/download/browser"
        ]
    }
    
    base_dir = "/home/ubuntu/google_flow_mcp/docs/drissionpage"
    
    for category_name, urls in pages.items():
        cat_dir = os.path.join(base_dir, category_name)
        os.makedirs(cat_dir, exist_ok=True)
        
        for idx, url in enumerate(urls, 1):
            print(f"Scraping {url} -> {category_name}")
            tab.get(url)
            
            title = f"{idx:02d}_{url.split('/')[-1]}"
            try:
                h1 = tab.ele('t:h1', timeout=5)
                if h1 and h1.text:
                    title = f"{idx:02d}_{h1.text}"
            except:
                pass
                
            title = sanitize_filename(title)
            file_path = os.path.join(cat_dir, f"{title}.md")
            
            try:
                article = tab.ele('t:article')
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
                    print(f"Failed to find article for {url}")
            except Exception as e:
                print(f"Error scraping {url}: {e}")
                
            time.sleep(1)

    browser.quit()

if __name__ == "__main__":
    main()
