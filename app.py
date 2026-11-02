import re
import difflib
from urllib.parse import urljoin
from datetime import datetime
from flask import Flask, request, Response, redirect
import requests
from bs4 import BeautifulSoup

app = Flask(__name__)

WIKI_API_URL = "https://en.wikipedia.org/api/rest_v1/page/html/"
WIKI_ROOT_URL = "https://en.wikipedia.org/"

def process_article(slug, is_download=False, image_level='section_top', show_alt=True):
    response = requests.get(f"{WIKI_API_URL}{slug}")
    if response.status_code != 200:
        return f"Error fetching article: {response.status_code}", response.status_code

    soup = BeautifulSoup(response.text, 'html.parser')

    title_tag = soup.find('title')
    page_name = title_tag.text if title_tag else slug.replace('_', ' ')
    
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

    # 0. Suppress Audio Files and Audio Figures
    for audio_tag in soup.find_all('audio'):
        audio_tag.decompose()
        
    for file_node in soup.find_all(attrs={'typeof': re.compile(r'mw:File')}):
        if 'Audio' in file_node.get('typeof', ''):
            file_node.decompose()
            continue
        img = file_node.find('img')
        if img and img.has_attr('src'):
            src = img['src'].lower()
            if any(ext in src for ext in ['.ogg', '.oga', '.mp3', '.flac', '.wav']):
                file_node.decompose()

    # 1. Find the main image unconditionally BEFORE structural cleanup
    main_image_node = None
    
    infobox = soup.find('table', class_=re.compile(r'\binfobox\b'))
    if infobox:
        for file_node in infobox.find_all(attrs={'typeof': re.compile(r'mw:File')}):
            img = file_node.find('img')
            if img:
                w = img.get('width') or img.get('data-file-width')
                if w and str(w).isdigit() and int(w) >= 150:
                    main_image_node = file_node.extract()
                    main_image_node.name = 'figure'
                    break

    if not main_image_node:
        for file_node in soup.find_all(attrs={'typeof': re.compile(r'mw:File')}):
            img = file_node.find('img')
            if img:
                w = img.get('width') or img.get('data-file-width')
                if w and str(w).isdigit() and int(w) >= 150:
                    main_image_node = file_node.extract()
                    main_image_node.name = 'figure'
                    break

    # 2. Convert all remaining mw:File nodes to standard <figure> tags
    for file_node in soup.find_all(attrs={'typeof': re.compile(r'mw:File')}):
        file_node.name = 'figure'

    # 3. Strip purely decorative or unwanted structural clutter completely
    destroy_entirely = [
        'IPA', 'noprint', 'reference', 'reflist', 'refbegin', 
        'hatnote', 'metadata', 'ambox', 'mbox', 'ombox', 'dmbox', 'fmbox', 
        'mwe-math-element', 'mw-highlight', 'toc', 'rellink', 'excerpt-hat', 
        'navbox', 'navbar', 'wgCoordinates', 'mw-jump-link',
        'infobox', 'gallery', 'sidebar', 'tsingle', 'trow', 'timeline-wrapper',
        'side-box-flex', 'box-Expand_section', 'geobox', 'mod-gallery'
    ]
    for cls in destroy_entirely:
        for el in soup.find_all(class_=cls):
            el.decompose()

    ids_to_remove = ['catlinks', 'footer', 'siteSub', 'header']
    for element_id in ids_to_remove:
        el = soup.find(id=element_id)
        if el:
            el.decompose()

    # 4. Number headings sequentially
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
        heading.string = f"Section {idx}: {original_text}"

    # 5. Strip unwanted sections
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

    # 6. Table Heuristic (Delete large tables entirely)
    for table in soup.find_all('table'):
        rows = table.find_all('tr')
        if len(rows) >= 5:
            table.decompose()

    # 7. Filter Images based on User Parameter (main_image_node is immune)
    if image_level == 'main':
        for fig in soup.find_all('figure'):
            fig.decompose()
    elif image_level == 'section_top':
        sections = soup.find_all('section')
        if sections:
            for sec in sections:
                for idx, fig in enumerate(sec.find_all('figure')):
                    if idx > 0:
                        fig.decompose()
        else:
            for idx, fig in enumerate(soup.find_all('figure')):
                if idx > 0:
                    fig.decompose()

    # 8. Strip specific identifier links
    for a in soup.find_all('a', href=True):
        if '(identifier)' in a['href'] or 'Special:BookSources' in a['href']:
            a.decompose()

    # 9. Absolutize URLs
    for tag in soup.find_all(['a', 'img', 'link']):
        if tag.name == 'a' and tag.has_attr('href'):
            tag['href'] = urljoin(WIKI_ROOT_URL, tag['href'])
        elif tag.name == 'img' and tag.has_attr('src'):
            tag['src'] = urljoin(WIKI_ROOT_URL, tag['src'])
            if tag.has_attr('srcset'):
                del tag['srcset']
        elif tag.name == 'link' and tag.has_attr('href'):
            tag['href'] = urljoin(WIKI_ROOT_URL, tag['href'])

    # 10. Format Alt Text, Captions, and Clearfix
    figures_to_format = soup.find_all('figure')
    if main_image_node:
        figures_to_format.append(main_image_node)

    for figure in figures_to_format:
        figcaption = figure.find('figcaption')
        img = figure.find('img')
        alt_text = img.get('alt', '').strip() if img else ""
        caption_text = figcaption.get_text(separator=" ", strip=True) if figcaption else ""

        # Logic: If no caption exists but alt text exists, promote alt text to caption
        if not figcaption and alt_text:
            figcaption = soup.new_tag('figcaption')
            figcaption.string = alt_text
            figure.append(figcaption)
            caption_text = alt_text
            # Clear alt text so it doesn't get rendered twice
            alt_text = ""

        show_this_alt = False
        if show_alt and alt_text and figcaption:
            similarity = difflib.SequenceMatcher(None, alt_text.lower(), caption_text.lower()).ratio()
            if similarity < 0.95:
                show_this_alt = True

        if figcaption:
            figcaption['style'] = "display: block; background-color: #f9f9f9; padding: 12px; border-left: 5px solid #0056b3; margin-top: 15px; font-size: 1.1em;"
            original_contents = list(figcaption.contents)
            figcaption.clear()

            cap_block = soup.new_tag('div')
            if show_this_alt:
                cap_block['style'] = "margin-bottom: 8px; padding-bottom: 8px; border-bottom: 1px solid #ddd;"
                
            cap_prefix = soup.new_tag('span')
            cap_prefix.string = "CAPTION: "
            cap_prefix['style'] = "color: #0056b3; font-weight: bold; text-transform: uppercase; margin-right: 8px;"
            cap_block.append(cap_prefix)
            
            for content in original_contents:
                cap_block.append(content)
                
            figcaption.append(cap_block)

            if show_this_alt:
                alt_block = soup.new_tag('div')
                alt_prefix = soup.new_tag('span')
                alt_prefix.string = "ALT TEXT: "
                alt_prefix['style'] = "color: #0056b3; font-weight: bold; text-transform: uppercase; margin-right: 8px;"
                alt_block.append(alt_prefix)
                alt_block.append(alt_text)
                figcaption.append(alt_block)
                
        # Inject clearfix to prevent orphaned text wrapping
        if figure.parent:
            clearfix = soup.new_tag('div')
            clearfix['style'] = "clear: both;"
            figure.insert_after(clearfix)

    body = soup.find('body') or soup

    # 11. Inject Spoken Wikipedia preamble
    preamble = soup.new_tag('p')
    preamble['style'] = "font-style: italic; font-weight: bold; font-size: 1.2em; background: #e0f2fe; padding: 15px; border-radius: 5px; margin-bottom: 25px;"
    preamble.string = f"This is the Spoken Wikipedia article on {page_name} read aloud by Wikipedia user __________"
    body.insert(0, preamble)

    # 12. Generate Top-Level Table of Contents
    surviving_h2s = soup.find_all('h2')
    toc_container = None
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

    # 13. Inject the Main Image
    if main_image_node:
        main_image_node['style'] = "float: right; clear: right; margin: 0 0 15px 20px; max-width: 45%;"
        if toc_container:
            toc_container.insert_after(main_image_node)
        else:
            preamble.insert_after(main_image_node)

    # 14. Inject Spoken Wikipedia outro and timestamp
    outro = soup.new_tag('p')
    outro['style'] = "font-style: italic; font-size: 1.1em; background: #e0f2fe; padding: 15px; border-radius: 5px; margin-top: 40px; clear: both;"
    outro.string = "This recording and the underlying text are available under the Creative Commons Attribution Share Alike 4.0 license. Additional terms may apply."
    body.append(outro)

    timestamp_footer = soup.new_tag('p')
    timestamp_footer['style'] = "font-style: italic; font-size: 0.9em; color: #555; margin-top: 15px; border-top: 1px solid #ccc; padding-top: 10px;"
    timestamp_footer.string = f"This page was based upon the version of the Wikipedia article {page_name} as it was on {date_str} at {time_str}."
    body.append(timestamp_footer)

    # 15. Inject base typography 
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

    # 16. Inject floating save button
    if not is_download:
        show_alt_str = 'true' if show_alt else 'false'
        ui_html = f"""
        <div id="spoken-view-ui" style="position: fixed; bottom: 20px; right: 20px; background: #fff; padding: 15px; border: 1px solid #ccc; box-shadow: 0 4px 6px rgba(0,0,0,0.1); z-index: 9999;">
            <a href="/download/{slug}?image_level={image_level}&show_alt={show_alt_str}" style="background: #0056b3; color: #fff; padding: 10px 15px; text-decoration: none; font-weight: bold; border-radius: 4px;">Save for Reading (Offline HTML)</a>
        </div>
        """
        ui_soup = BeautifulSoup(ui_html, 'html.parser')
        body.append(ui_soup)

    return str(soup), 200

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        user_input = request.form.get('wiki_input', '').strip()
        image_level = request.form.get('image_level', 'section_top')
        show_alt = 'true' if request.form.get('show_alt') else 'false'

        if 'wikipedia.org/wiki/' in user_input:
            slug = user_input.split('/wiki/')[-1]
        else:
            slug = user_input
        return redirect(f"/view/{slug}?image_level={image_level}&show_alt={show_alt}")

    return """
    <html>
        <head><title>Spoken View</title></head>
        <body style="font-family: sans-serif; max-width: 600px; margin: 40px auto; line-height: 1.6;">
            <h1>Spoken View</h1>
            <p>Enter an English Wikipedia article URL or exact name to generate a clutter-free, read-aloud version.</p>
            <form method="POST">
                <input type="text" name="wiki_input" placeholder="e.g., Bicycle or https://en.wikipedia.org/wiki/Bicycle" style="width: 100%; padding: 10px; margin-bottom: 15px;" required>
                
                <p style="margin-bottom: 5px; font-weight: bold;">Please select how many images to display:</p>
                <div style="margin-bottom: 15px;">
                    <label style="display: block; margin-bottom: 5px;"><input type="radio" name="image_level" value="main"> Main article image only</label>
                    <label style="display: block; margin-bottom: 5px;"><input type="radio" name="image_level" value="section_top" checked> Top image per section (always includes main image)</label>
                    <label style="display: block; margin-bottom: 5px;"><input type="radio" name="image_level" value="all"> All images</label>
                </div>
                
                <div style="margin-bottom: 20px;">
                    <label style="font-weight: bold;"><input type="checkbox" name="show_alt" value="true" checked> Show alt text (when distinct from caption)</label>
                </div>

                <button type="submit" style="padding: 10px 20px; background: #0056b3; color: white; border: none; font-weight: bold; cursor: pointer;">Generate View</button>
            </form>
        </body>
    </html>
    """

@app.route('/view/<path:slug>')
def view_article(slug):
    image_level = request.args.get('image_level', 'section_top')
    show_alt = request.args.get('show_alt', 'true') == 'true'
    
    html_content, status_code = process_article(slug, is_download=False, image_level=image_level, show_alt=show_alt)
    if status_code != 200:
        return html_content, status_code
    return Response(html_content, mimetype='text/html')

@app.route('/download/<path:slug>')
def download_article(slug):
    image_level = request.args.get('image_level', 'section_top')
    show_alt = request.args.get('show_alt', 'true') == 'true'

    html_content, status_code = process_article(slug, is_download=True, image_level=image_level, show_alt=show_alt)
    if status_code != 200:
        return html_content, status_code
    
    return Response(
        html_content,
        mimetype='text/html',
        headers={"Content-Disposition": f"attachment; filename={slug}_Spoken_View.html"}
    )

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)