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

    start_url = "https://www.drissionpage.cn/SessionPage/intro"
    print(f"Loading {start_url} ...")
    tab.get(start_url)
    
    # Wait for sidebar to load
    sidebar = tab.ele('.theme-doc-sidebar-menu', timeout=10)
    if not sidebar:
        print("Sidebar not found.")
        browser.quit()
        return
        
    categories = tab.eles('c:theme-doc-sidebar-item-category-level-1')
    
    base_dir = "/home/ubuntu/google_flow_mcp/docs/drissionpage"
    os.makedirs(base_dir, exist_ok=True)
    
    pages_to_scrape = []
    
    # In Docusaurus, when we navigate to a module, ALL its categories are in the sidebar
    # We will just scrape all categories found in the sidebar, since we are in the SessionPage module
    # But just in case, we will check if the text contains SessionPage or we can just take all of them.
    # To be safe, we take all of them because a module might have subcategories.
    for category_idx, category_ele in enumerate(categories, 1):
        collapsible = category_ele.ele('t:div')
        if not collapsible:
            continue
            
        cat_title_ele = collapsible.ele('t:a')
        if not cat_title_ele:
            continue
            
        cat_title_full = cat_title_ele.text
        
        # We only want SessionPage related categories
        if "SessionPage" not in cat_title_full:
            continue
            
        cat_title = sanitize_filename(f"{category_idx:02d}_{cat_title_full}")
        
        # Expand if not expanded
        is_expanded = cat_title_ele.attr('aria-expanded') == 'true'
        if not is_expanded:
            try:
                cat_title_ele.click()
                time.sleep(0.5)
            except:
                pass
        
        sub_list = category_ele.ele('t:ul')
        if sub_list:
            links = sub_list.eles('t:a')
            for link_idx, link in enumerate(links, 1):
                title = sanitize_filename(f"{link_idx:02d}_{link.text}")
                href = link.link
                if href:
                    pages_to_scrape.append({
                        "category": cat_title,
                        "title": title,
                        "url": href
                    })

    print(f"Found {len(pages_to_scrape)} pages to scrape for SessionPage.")
    
    for page_info in pages_to_scrape:
        cat_dir = os.path.join(base_dir, page_info['category'])
        os.makedirs(cat_dir, exist_ok=True)
        
        file_path = os.path.join(cat_dir, f"{page_info['title']}.md")
        print(f"Scraping {page_info['url']} -> {file_path}")
        
        tab.get(page_info['url'])
        article = tab.ele('t:article', timeout=10)
        
        if article:
            html_content = article.html
            md_content = markdownify.markdownify(
                html_content, 
                heading_style="ATX", 
                strip=['script', 'style', 'button']
            )
            
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(md_content)
        else:
            print(f"Failed to find article for {page_info['url']}")
            
        time.sleep(1)

    browser.quit()

if __name__ == "__main__":
    main()
