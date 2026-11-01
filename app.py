import re
from urllib.parse import urljoin
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

    # 2. Table Heuristic: Remove complex tables (>= 5 rows), keep simple lists
    for table in soup.find_all('table'):
        rows = table.find_all('tr')
        if len(rows) >= 5:
            table.decompose()

    # 3. Strip specific identifier links (ISBN, PMID, etc.) 
    for a in soup.find_all('a', href=True):
        if '(identifier)' in a['href'] or 'Special:BookSources' in a['href']:
            a.decompose()

    # 4. Absolutize URLs for offline viewing and live-served images
    for tag in soup.find_all(['a', 'img', 'link']):
        if tag.name == 'a' and tag.has_attr('href'):
            tag['href'] = urljoin(WIKI_ROOT_URL, tag['href'])
        elif tag.name == 'img' and tag.has_attr('src'):
            tag['src'] = urljoin(WIKI_ROOT_URL, tag['src'])
            # Remove srcset so offline HTML relies exclusively on the absolute src
            if tag.has_attr('srcset'):
                del tag['srcset']
        elif tag.name == 'link' and tag.has_attr('href'):
            tag['href'] = urljoin(WIKI_ROOT_URL, tag['href'])

    # 5. Make Captions Prominent for TTS / Human Readers
    for figure in soup.find_all('figure'):
        figcaption = figure.find('figcaption')
        if figcaption:
            # High-contrast visual cue for readers
            figcaption['style'] = "display: block; background-color: #f9f9f9; padding: 12px; border-left: 5px solid #0056b3; font-weight: bold; margin-top: 15px; font-size: 1.1em;"
            
            prefix = soup.new_tag('span')
            prefix.string = "CAPTION: "
            prefix['style'] = "color: #0056b3; text-transform: uppercase; margin-right: 8px;"
            figcaption.insert(0, prefix)

    # 6. Inject base typography 
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

    # 7. Inject floating save button (only for the live web view)
    if not is_download:
        ui_html = f"""
        <div id="spoken-view-ui" style="position: fixed; bottom: 20px; right: 20px; background: #fff; padding: 15px; border: 1px solid #ccc; box-shadow: 0 4px 6px rgba(0,0,0,0.1); z-index: 9999;">
            <a href="/download/{slug}" style="background: #0056b3; color: #fff; padding: 10px 15px; text-decoration: none; font-weight: bold; border-radius: 4px;">Save for Reading (Offline HTML)</a>
        </div>
        """
        ui_soup = BeautifulSoup(ui_html, 'html.parser')
        if soup.body:
            soup.body.append(ui_soup)
        else:
            soup.append(ui_soup)

    return str(soup), 200

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        user_input = request.form.get('wiki_input', '').strip()
        # Parse slug from full URL or use direct string
        if 'wikipedia.org/wiki/' in user_input:
            slug = user_input.split('/wiki/')[-1]
        else:
            slug = user_input
        return redirect(f"/view/{slug}")

    return """
    <html>
        <body style="font-family: sans-serif; max-width: 600px; margin: 40px auto; line-height: 1.6;">
            <h1>Spoken View</h1>
            <p>Enter an English Wikipedia article URL or exact name to generate a clutter-free, read-aloud version.</p>
            <form method="POST">
                <input type="text" name="wiki_input" placeholder="e.g., Cat or https://en.wikipedia.org/wiki/Cat" style="width: 100%; padding: 10px; margin-bottom: 10px;" required>
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