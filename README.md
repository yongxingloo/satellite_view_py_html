# satellite_view_py_html

This project is a small satellite timelapse viewer built with a Flask backend and an HTML/JavaScript frontend. It lets you:

- choose an area of interest on a map
- search remote STAC catalogs for matching scenes
- preview those scenes as a timelapse
- inspect source URLs for the selected frame
- export the current sequence as a ZIP of frames or an animated GIF

## Quick-start guide

From the repository root, choose one of these run modes:

1. **Installed package run (recommended)**
   ```bash
   pip install .
   satellite_view
   ```
2. **Requirements-based run (no package install command)**
   ```bash
   pip install -r requirements.txt
   python app.py
   ```


## Project structure

- `satellite_view/webapp.py`
  The Flask application. It serves the page, searches STAC APIs, normalizes scene data, builds preview URLs, and handles exports.

- `satellite_view/cli.py`
  The package CLI entry point. It starts the app server and opens the browser by default.

- `satellite_view/templates/index.html`
  The main page template. It defines the visible UI structure for filters, map, analytics, scene cards, and the preview panel.

- `satellite_view/static/app.js`
  The frontend controller. It manages map drawing, area selection, search requests, timeline rendering, scene selection, playback, and export button behavior.

- `satellite_view/static/styles.css`
  The application stylesheet. It defines layout, spacing, map toolbars, scene cards, timeline visuals, and responsive behavior.

- `pyproject.toml`
  Packaging metadata, dependencies, and the `satellite_view` console script declaration.

- `requirements.txt`
  Dependency list for the direct requirements-based run flow.

- [.gitignore](D:\Idea League\ETHZ\AI Assisted Coding\satellite_view_py_html\.gitignore)
  Git ignore rules for Python cache files.

## Backend flow

1. Flask renders `index.html` and injects `APP_CONFIG` with defaults such as the default bbox and dates.
2. The frontend sends `/api/search` requests with the current filters and AOI.
3. `app.py` queries the selected STAC APIs, follows pagination, and converts raw items into normalized scene objects.
4. The backend computes timeline stats and returns scenes plus metadata to the frontend.
5. Export routes download remote frame assets and package them as ZIP or GIF files.

## Frontend flow

1. `static/app.js` starts Leaflet with the configured default view.
2. The default bbox is drawn immediately so the app opens with a ready-to-search AOI.
3. Users can refine the AOI by drawing a rectangle or using the current map view.
4. Search results are rendered as scene cards, timeline dots, and map footprints.
5. The preview panel updates when a scene is selected or when playback advances.

## Notes on important concepts

- `browser_url`
  The STAC item URL for the selected scene.

- `frame_url`
  The preferred preview/render URL used for the visible frame, often a TiTiler-generated URL.

- `fallback_frame_url`
  A simpler preview image used when dynamic AOI rendering is unavailable.

- `coverage_score`
  A fractional measure of how much of the selected AOI is covered by a given scene.

## Why the code is commented

The codebase now includes:

- module-level explanations in Python
- function docstrings in the backend
- section comments in HTML, CSS, and JavaScript

The aim is that someone new to the project can quickly understand both the high-level architecture and the intent of each major section without reverse-engineering everything from scratch.
