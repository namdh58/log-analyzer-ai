# AI Log Analysis Assistant — Architecture Deck

A PPTX-style, keyboard-driven slide deck for a technical design review of the AI Log Analysis
Assistant. Every claim on every slide is drawn from the real system's source code and design
decisions — nothing is invented for the deck.

## Run it

```
npm install
npm run dev
```

Then open http://localhost:5174

`npm install` has nothing to install — zero dependencies. `npm run dev` starts a tiny built-in
Node static file server (`server.js`, stdlib only) serving `public/`.

## Controls

| Key | Action |
|---|---|
| `→` / `Space` | Next slide |
| `←` | Previous slide |
| `Home` | First slide |
| `End` | Last slide |
| Click left/right edge of the deck | Previous / next |
| Progress dots (bottom) | Jump to any slide |

## Structure

```
ai-log-analyst-slides/
├── package.json     # npm run dev -> node server.js
├── server.js         # zero-dependency static file server
└── public/
    ├── index.html    # 18 slides, one <section class="slide"> each
    ├── style.css      # 16:9 slide engine + dark theme + diagram components
    └── script.js      # slide controller: keyboard nav, dots, progress bar
```

The deck is locked to a true 16:9 box (letterboxed on any screen) via pure CSS
(`width: min(177.78vh, 100vw); height: min(100vh, 56.25vw)`), with only one `.slide.active`
visible at a time — no page scrolling, no scroll-snap.

## Diagrams

Every diagram (layered architecture, pipeline flow, sequence diagram, schema tables) is built
from plain `<div>`s with flexbox/grid, borders, and text-arrow connectors — no Mermaid, no SVG
diagram tooling, no charting library. See the component classes in `style.css`: `.flow`,
`.stack`/`.layer`, `.seq`, `.schema`, `.compare-col`.

## Markdown version

`PRESENTATION.md` mirrors the same 18 slides as a plain Marp-compatible markdown file (`---`
slide breaks) — open it directly in any markdown viewer, or render it as real slides/PDF with
[Marp](https://marp.app/) if you want that: `npx @marp-team/marp-cli PRESENTATION.md -o slides.pdf`.
No install needed just to read it.

## Content source

Slide content (the 9-step reasoning flow, the 8 deterministic signal detectors, the LangGraph
orchestration graph, the 4 chaos scenarios, the "no vector DB" retrieval decision, the real
hallucination bugs fixed in the grounding layer) is drawn directly from the `observability-ai`
project's source and its `PROGRESS.md` decision log.
