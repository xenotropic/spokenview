# Spoken View

Creates a normalized view of a Wikipedia article for reading.

## Overview
Currently, there are various methods floating around for creating a version of a Wikipedia article that is suitable for being read aloud. This project endeavors to make a view for humans to read it with a certain level of simplification. The typical intent is for the Spoken Wikipedia project, which currently provides instructions to paste in a certain chunk of JavaScript. 

This tool operates as a web service to replace client-side script execution. It parses the Wikipedia REST API Parsoid HTML and normalizes the DOM. It removes navigation elements, metadata, complex tables, and visual clutter that distract from the primary text. It additionally highlights image captions and allows users to download a static HTML file for offline reading.

## Architecture
- Python 3.11
- Flask (Web framework)
- BeautifulSoup 4 (DOM manipulation)
- Requests (API ingestion)

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