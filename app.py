import re
from urllib.parse import urljoin
from datetime import datetime
from flask import Flask, request, Response, redirect
import requests
from bs4 import BeautifulSoup

app = Flask(__name__)

# Core endpoints
WIKI_API_URL = "https://en.wikipedia.org/api/rest_v1/page/html/"
WIKI_ROOT_URL = "https://en.wikipedia.org/"

def process_article(slug, is_download=False):
    """Fetches Parsoid HTML, cleans the DOM, and injects reading styles."""
    response = requests.get(f"{WIKI_API_URL}{slug}")
    if response.status_code != 200:
        return f"Error fetching article: {response.status_code}", response.status_code

    soup = BeautifulSoup(response.text, 'html.parser')

    # Get proper page title if available for templates
    title_tag = soup.find('title')
    page_name = title_tag.text if title_tag else slug.replace('_', ' ')
    
    # Extract modification timestamp for the footer
    meta_time = soup.find('meta', property='dc:modified')
    if meta_time and meta_time.get('content'):
        try:
            dt = datetime.strptime(meta_time['content'][:19], "%Y-%m-%dT%H:%M:%S")
            date_str = dt.strftime("%B %d, %Y")
            time_str = dt.strftime("%H:%M UTC")
        except ValueError:
            date_str = "[Date]"
            time_str = "[Time]"
    else:
        date_str = "[Date]"
        time_str = "[Time]"

    # 0. Adjust Title tag to prepend "SpokenView:" and remove <base> tag
    base_tag = soup.find('base')
    if base_tag:
        base_tag.decompose()

    if title_tag:
        title_tag.string = f"SpokenView: {page_name}"
    else:
        head = soup.find('head')
        if not head:
            head = soup.new_tag('head')
            soup.insert(0, head)
        title_tag = soup.new_tag('title')
        title_tag.string = f"SpokenView: {page_name}"
        head.append(title_tag)

    # 1. Strip structural clutter, sidebars, navigation, and IPA pronunciations
    classes_to_remove = [
        'IPA', 'noprint', 'reference', 'reflist', 'refbegin', 'infobox',
        'hatnote', 'gallery', 'sidebar', 'tsingle', 'trow', 'timeline-wrapper',
        'side-box-flex', 'box-Expand_section', 'metadata', 'ambox', 'mbox',
        'ombox', 'dmbox', 'fmbox', 'geobox', 'mod-gallery', 'mwe-math-element',
        'mw-highlight', 'toc', 'rellink', 'excerpt-hat', 'navbox', 'navbar',
        'wgCoordinates', 'mw-jump-link'
    ]
    for cls in classes_to_remove:
        for el in soup.find_all(class_=cls):
            el.decompose()

    ids_to_remove = ['catlinks', 'footer', 'siteSub', 'header']
    for element_id in ids_to_remove:
        el = soup.find(id=element_id)
        if el:
            el.decompose()

    # 2. Number headings sequentially to match Wikipedia's native structure
    h2_data = []
    h2_tags = soup.find_all('h2')
    for idx, heading in enumerate(h2_tags, start=1):
        original_text = heading.get_text().strip()
        if not heading.get('id'):
            heading['id'] = f"spoken-section-{idx}"
            
        h2_data.append({
            'tag': heading,
            'original_text': original_text,
            'id': heading.get('id')
        })
        # Modify DOM to explicitly write out the section number
        heading.string = f"Section {idx}: {original_text}"

    # 3. Strip unwanted sections (See also, Notes, References, External links, Further reading)
    sections_to_remove = ['see also', 'notes', 'references', 'external links', 'further reading']
    for data in h2_data:
        heading = data['tag']
        heading_lower = data['original_text'].lower()
        if heading_lower in sections_to_remove:
            parent_section = heading.find_parent('section')
            if parent_section:
                parent_section.decompose()
            else:
                curr = heading.find_next_sibling()
                heading.decompose()
                while curr and curr.name not in ['h1', 'h2', 'h3', 'h4']:
                    next_el = curr.find_next_sibling()
                    curr.decompose()
                    curr = next_el

    # 4. Table Heuristic: Remove complex tables (>= 5 rows), keep simple lists
    for table in soup.find_all('table'):
        rows = table.find_all('tr')
        if len(rows) >= 5:
            table.decompose()

    # 5. Strip specific identifier links (ISBN, PMID, etc.) 
    for a in soup.find_all('a', href=True):
        if '(identifier)' in a['href'] or 'Special:BookSources' in a['href']:
            a.decompose()

    # 6. Absolutize URLs for offline viewing and live-served images
    for tag in soup.find_all(['a', 'img', 'link']):
        if tag.name == 'a' and tag.has_attr('href'):
            tag['href'] = urljoin(WIKI_ROOT_URL, tag['href'])
        elif tag.name == 'img' and tag.has_attr('src'):
            tag['src'] = urljoin(WIKI_ROOT_URL, tag['src'])
            if tag.has_attr('srcset'):
                del tag['srcset']
        elif tag.name == 'link' and tag.has_attr('href'):
            tag['href'] = urljoin(WIKI_ROOT_URL, tag['href'])

    # 7. Make Captions Prominent for TTS / Human Readers
    for figure in soup.find_all('figure'):
        figcaption = figure.find('figcaption')
        if figcaption:
            figcaption['style'] = "display: block; background-color: #f9f9f9; padding: 12px; border-left: 5px solid #0056b3; font-weight: bold; margin-top: 15px; font-size: 1.1em;"
            prefix = soup.new_tag('span')
            prefix.string = "CAPTION: "
            prefix['style'] = "color: #0056b3; text-transform: uppercase; margin-right: 8px;"
            figcaption.insert(0, prefix)

    body = soup.find('body') or soup

    # 8. Inject Spoken Wikipedia preamble
    preamble = soup.new_tag('p')
    preamble['style'] = "font-style: italic; font-weight: bold; font-size: 1.2em; background: #e0f2fe; padding: 15px; border-radius: 5px; margin-bottom: 25px;"
    preamble.string = f"This is the Spoken Wikipedia article on {page_name} read aloud by Wikipedia user __________"
    body.insert(0, preamble)

    # 9. Generate Top-Level Table of Contents (H2 only)
    surviving_h2s = soup.find_all('h2')
    if surviving_h2s:
        toc_container = soup.new_tag('div')
        toc_container['style'] = "background: #f8f9fa; padding: 15px; margin: 20px 0; border: 1px solid #a2a9b1; border-radius: 2px;"
        
        toc_title = soup.new_tag('h2')
        toc_title.string = "Contents"
        toc_title['style'] = "margin-top: 0; font-size: 1.2em; border-bottom: none;"
        toc_container.append(toc_title)
        
        toc_list = soup.new_tag('ul')
        toc_list['style'] = "list-style-type: none; padding-left: 0; margin-bottom: 0;"
        
        for h2 in surviving_h2s:
            li = soup.new_tag('li')
            li['style'] = "margin-bottom: 6px;"
            
            a_tag = soup.new_tag('a')
            a_tag['href'] = f"#{h2.get('id')}"
            a_tag['style'] = "text-decoration: none; color: #0645ad; font-weight: bold;"
            
            # Format as "1. Name" instead of "Section 1: Name" for the TOC
            text = h2.get_text()
            if text.startswith("Section "):
                toc_text = text.replace("Section ", "", 1).replace(":", ".", 1)
            else:
                toc_text = text
            a_tag.string = toc_text
            
            li.append(a_tag)
            toc_list.append(li)
            
        toc_container.append(toc_list)
        preamble.insert_after(toc_container)

    # 10. Inject Spoken Wikipedia outro and timestamp
    outro = soup.new_tag('p')
    outro['style'] = "font-style: italic; font-size: 1.1em; background: #e0f2fe; padding: 15px; border-radius: 5px; margin-top: 40px;"
    outro.string = "This recording and the underlying text are available under the Creative Commons Attribution Share Alike 4.0 license. Additional terms may apply."
    body.append(outro)

    timestamp_footer = soup.new_tag('p')
    timestamp_footer['style'] = "font-style: italic; font-size: 0.9em; color: #555; margin-top: 15px; border-top: 1px solid #ccc; padding-top: 10px;"
    timestamp_footer.string = f"This page was based upon the version of the Wikipedia article {page_name} as it was on {time_str} and {date_str}."
    body.append(timestamp_footer)

    # 11. Inject base typography 
    head = soup.find('head')
    if not head:
        head = soup.new_tag('head')
        soup.insert(0, head)
    
    style = soup.new_tag('style')
    style.string = """
        body { font-family: sans-serif; line-height: 1.6; max-width: 800px; margin: 0 auto; padding: 20px; color: #111; } 
        img { max-width: 100%; height: auto; }
        figure { margin-left: 0; margin-right: 0; }
    """
    head.append(style)

    # 12. Inject floating save button (only for live view)
    if not is_download:
        ui_html = f"""
        <div id="spoken-view-ui" style="position: fixed; bottom: 20px; right: 20px; background: #fff; padding: 15px; border: 1px solid #ccc; box-shadow: 0 4px 6px rgba(0,0,0,0.1); z-index: 9999;">
            <a href="/download/{slug}" style="background: #0056b3; color: #fff; padding: 10px 15px; text-decoration: none; font-weight: bold; border-radius: 4px;">Save for Reading (Offline HTML)</a>
        </div>
        """
        ui_soup = BeautifulSoup(ui_html, 'html.parser')
        body.append(ui_soup)

    return str(soup), 200

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        user_input = request.form.get('wiki_input', '').strip()
        if 'wikipedia.org/wiki/' in user_input:
            slug = user_input.split('/wiki/')[-1]
        else:
            slug = user_input
        return redirect(f"/view/{slug}")

    return """
    <html>
        <head><title>Spoken View</title></head>
        <body style="font-family: sans-serif; max-width: 600px; margin: 40px auto; line-height: 1.6;">
            <h1>Spoken View</h1>
            <p>Enter an English Wikipedia article URL or exact name to generate a clutter-free, read-aloud version.</p>
            <form method="POST">
                <input type="text" name="wiki_input" placeholder="e.g., Bicycle or https://en.wikipedia.org/wiki/Bicycle" style="width: 100%; padding: 10px; margin-bottom: 10px;" required>
                <button type="submit" style="padding: 10px 20px; background: #0056b3; color: white; border: none; font-weight: bold; cursor: pointer;">Generate View</button>
            </form>
        </body>
    </html>
    """

@app.route('/view/<path:slug>')
def view_article(slug):
    html_content, status_code = process_article(slug, is_download=False)
    if status_code != 200:
        return html_content, status_code
    return Response(html_content, mimetype='text/html')

@app.route('/download/<path:slug>')
def download_article(slug):
    html_content, status_code = process_article(slug, is_download=True)
    if status_code != 200:
        return html_content, status_code
    
    return Response(
        html_content,
        mimetype='text/html',
        headers={"Content-Disposition": f"attachment; filename={slug}_Spoken_View.html"}
    )

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)