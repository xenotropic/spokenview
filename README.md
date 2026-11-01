# Spoken View

Creates a normalized view of a Wikipedia article for reading.

## Overview

Currently, there are various methods floating around for creating a version of a Wikipedia article that is suitable for being read aloud. This project endeavors to make a view for humans to read it with a certain level of simplification. The typical intent is for the Spoken Wikipedia project, which currently provides instructions to paste in a certain chunk of JavaScript.

This tool operates as a web service to replace client-side script execution. It parses the Wikipedia REST API Parsoid HTML and normalizes the DOM. It removes navigation elements, metadata, complex tables, and visual clutter that distract from the primary text. It additionally highlights image captions and allows users to download a static HTML file for offline reading.

## DOM Transformations

To optimize the document for reading aloud, the service performs the following specific modifications to the fetched Wikipedia article:

### Additions and Injections
* **Title:** Prepends "SpokenView: " to the HTML `<title>` tag.
* **Preamble:** Injects introductory text at the top of the article body: "This is the Spoken Wikipedia article on [Page Name] read aloud by Wikipedia user __________".
* **Outro:** Injects licensing text at the bottom of the article body: "This recording and the underlying text are available under the Creative Commons Attribution Share Alike 4.0 license. Additional terms may apply."
* **Captions:** Prepends the text "CAPTION: " to all `<figcaption>` elements and applies high-contrast styling to separate them visually from body text.
* **URL Resolution:** Converts all relative URLs (links, images, and stylesheets) to absolute URLs pointing to `https://en.wikipedia.org` to ensure offline functionality.
* **Interface:** Injects a floating "Save for Reading" button in the live web view for offline HTML downloading.

### Removals and Deletions
* **Structural Clutter:** Removes standard Wikipedia interface and layout elements, including sidebars, navigation boxes, tables of contents, coordinates, jump links, headers, footers, and category links.
* **Reading Disruptions:** Removes inline citations (`.reference`), reference lists, hatnotes, infoboxes, warning/message boxes (`.ambox`, `.mbox`, etc.), math elements, and International Phonetic Alphabet (IPA) pronunciations.
* **Complex Tables:** Removes any HTML `<table>` containing 5 or more rows. Simple tables (fewer than 5 rows) are retained.
* **Appendices:** Wipes the following headings and their entire associated sections:
  * See also
  * Notes
  * References
  * External links
  * Further reading
* **Identifiers:** Removes specific publication identifier links (e.g., ISBN, PMID, DOI) that match `(identifier)` or `Special:BookSources`.

## Architecture

* Python 3.11
* Flask (Web framework)
* BeautifulSoup 4 (DOM manipulation)
* Requests (API ingestion)

## Deployment (Wikimedia Toolforge)

This service is configured for the Wikimedia Toolforge Kubernetes Python backend.

Code should be deployed to `~/www/python/src`.

Dependencies must be installed via a Toolforge interactive shell:
`webservice --backend=kubernetes python3.11 shell`

Service management commands:
`webservice --backend=kubernetes python3.11 start`
`webservice --backend=kubernetes python3.11 restart`

## License

MIT License