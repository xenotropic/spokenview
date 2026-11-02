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
    for file_node in soup.find_all(attrs={'typeof': re.compile(r'mw:File')}):
        img = file_node.find('img')
        if img:
            # Skip tiny decorative icons
            w = img.get('width') or img.get('data-file-width')
            if w and str(w).isdigit() and int(w) < 100:
                continue
            main_image_node = file_node.extract()
            main_image_node.name = 'figure'
            break

    # 2. Convert all remaining mw:File nodes to standard <figure> tags
    for file_node in soup.find_all(attrs={'typeof': re.compile(r'mw:File')}):
        file_node.name = 'figure'

    # 3. Strip purely decorative or unwanted structural clutter
    destroy_entirely = [
        'IPA', 'noprint', 'reference', 'reflist', 'refbegin', 
        'hatnote', 'metadata', 'ambox', 'mbox', 'ombox', 'dmbox', 'fmbox', 
        'mwe-math-element', 'mw-highlight', 'toc', 'rellink', 'excerpt-hat', 
        'navbox', 'navbar', 'wgCoordinates', 'mw-jump-link'
    ]
    for cls in destroy_entirely:
        for el in soup.find_all(class_=cls):
            el.decompose()

    ids_to_remove = ['catlinks', 'footer', 'siteSub', 'header']
    for element_id in ids_to_remove:
        el = soup.find(id=element_id)
        if el:
            el.decompose()

    # 4. Strip large structural containers but RESCUE their figures (e.g., infoboxes)
    rescue_figures_from = [
        'infobox', 'gallery', 'sidebar', 'tsingle', 'trow', 'timeline-wrapper',
        'side-box-flex', 'box-Expand_section', 'geobox', 'mod-gallery'
    ]
    for cls in rescue_figures_from:
        for el in soup.find_all(class_=cls):
            if el.parent is not None:
                figures = el.find_all('figure')
                for fig in figures:
                    el.insert_before(fig.extract())
                el.decompose()

    # 5. Number headings sequentially
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

    # 6. Strip unwanted sections
    sections_to_remove = ['see also', 'notes', 'references', 'external links', 'further reading']
    for data in h2_data:
        heading = data['tag']
        heading_lower = data['original_text'].lower()
        if heading_lower in sections_to_remove:
            parent_section = heading.find_parent('section')
            if parent_section:
                for fig in parent_section.find_all('figure'):
                    parent_section.insert_before(fig.extract())
                parent_section.decompose()
            else:
                curr = heading.find_next_sibling()
                heading.decompose()
                while curr and curr.name not in ['h1', 'h2', 'h3', 'h4']:
                    next_el = curr.find_next_sibling()
                    for fig in curr.find_all('figure'):
                        curr.insert_before(fig.extract())
                    curr.decompose()
                    curr = next_el

    # 7. Table Heuristic (rescue figures first)
    for table in soup.find_all('table'):
        if table.parent is not None:
            rows = table.find_all('tr')
            if len(rows) >= 5:
                for fig in table.find_all('figure'):
                    table.insert_before(fig.extract())
                table.decompose()

    # 8. Filter Images based on User Parameter
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

    body = soup.find('body') or soup

    # 9. Re-inject the Main Image unconditionally so it gets formatted by URL & Caption logic
    if main_image_node:
        body.insert(0, main_image_node)

    # 10. Strip specific identifier links
    for a in soup.find_all('a', href=True):
        if '(identifier)' in a['href'] or 'Special:BookSources' in a['href']:
            a.decompose()

    # 11. Absolutize URLs
    for tag in soup.find_all(['a', 'img', 'link']):
        if tag.name == 'a' and tag.has_attr('href'):
            tag['href'] = urljoin(WIKI_ROOT_URL, tag['href'])
        elif tag.name == 'img' and tag.has_attr('src'):
            tag['src'] = urljoin(WIKI_ROOT_URL, tag['src'])
            if tag.has_attr('srcset'):
                del tag['srcset']
        elif tag.name == 'link' and tag.has_attr('href'):
            tag['href'] = urljoin(WIKI_ROOT_URL, tag['href'])

    # 12. Format Alt Text and Captions
    for figure in soup.find_all('figure'):
        figcaption = figure.find('figcaption')
        img = figure.find('img')
        alt_text = img.get('alt', '').strip() if img else ""
        caption_text = figcaption.get_text(separator=" ", strip=True) if figcaption else ""

        # Filter out identical or heavily duplicated alt text (>95% similar)
        show_this_alt = False
        if show_alt and alt_text:
            similarity = difflib.SequenceMatcher(None, alt_text.lower(), caption_text.lower()).ratio()
            if similarity < 0.95:
                show_this_alt = True

        # Handle images lacking an original caption
        if not figcaption:
            if show_this_alt:
                figcaption = soup.new_tag('figcaption')
                figcaption['style'] = "display: block; background-color: #f9f9f9; padding: 12px; border-left: 5px solid #0056b3; margin-top: 15px; font-size: 1.1em;"
                figure.append(figcaption)
                
                alt_block = soup.new_tag('div')
                alt_prefix = soup.new_tag('span')
                alt_prefix.string = "ALT TEXT: "
                alt_prefix['style'] = "color: #0056b3; font-weight: bold; text-transform: uppercase; margin-right: 8px;"
                alt_block.append(alt_prefix)
                alt_block.append(alt_text)
                figcaption.append(alt_block)
            continue

        figcaption['style'] = "display: block; background-color: #f9f9f9; padding: 12px; border-left: 5px solid #0056b3; margin-top: 15px; font-size: 1.1em;"
        original_contents = list(figcaption.contents)
        figcaption.clear()

        # Build Caption Block
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

        # Build Alt Block directly below the caption
        if show_this_alt:
            alt_block = soup.new_tag('div')
            alt_prefix = soup.new_tag('span')
            alt_prefix.string = "ALT TEXT: "
            alt_prefix['style'] = "color: #0056b3; font-weight: bold; text-transform: uppercase; margin-right: 8px;"
            alt_block.append(alt_prefix)
            alt_block.append(alt_text)
            figcaption.append(alt_block)

    # 13. Inject Spoken Wikipedia preamble (pushes the main image down, making Preamble first)
    preamble = soup.new_tag('p')
    preamble['style'] = "font-style: italic; font-weight: bold; font-size: 1.2em; background: #e0f2fe; padding: 15px; border-radius: 5px; margin-bottom: 25px;"
    preamble.string = f"This is the Spoken Wikipedia article on {page_name} read aloud by Wikipedia user __________"
    body.insert(0, preamble)

    # 14. Generate Top-Level Table of Contents
    surviving_h2s = soup.find_all('h2')
    if surviving_h2s