# Investigation (research) dispatch — shared clauses (R-INVEST)

> Seed = host A's `antigravity_wrapper.py` constant `AGY_WEB_EVIDENCE_CLAUSE` (2026-09-19), byte-identical below.
> Scope: any Google-family dispatch that may read the web — A's `--web` research agent (agy `read_url_content` /
> `search_web`); B's explicitly web-authorized raw investigation (gemini `web_fetch` / `google_web_search`).
> Not a review clause: review legs read only the reviewed tree (`R-CONTAIN`; D-9 decides the gemini policy rows).
> Placeholders: none. Vendoring rule: `README.md` § How a host uses a revision.

## web-evidence (R-INVEST)

```text
WEB EVIDENCE PROCEDURE (appended by the caller to every research dispatch; it binds every external fact in your answer). search_web returns a model-written summary and grounding-redirect links: a POINTER to sources, never a citation. For every fact you take from the web, call read_url_content on the source page itself (the official document, the version-tagged source file, the release note or the repository page) and cite the exact URL you fetched together with the date or version string visible ON that page. Never write a URL you did not fetch, a placeholder such as `https://example.com/...`, or a bare year in place of a page date. If the fetch fails or the page shows no date or version, report that fact as UNSURE and name the URL you tried. Local file facts come first, cited as path:line; web facts follow, each with its fetched URL and page date.
```

## order

The host appends `web-evidence` LAST, after the caller's own prompt text and one blank line.
Evidence custody, redaction and verification follow [R-INVEST](../reference/review-rules.md#R-INVEST).
On a gemini route the tool names read `web_fetch` for the page fetch and `google_web_search` for the summary; a host
renderer substitutes the names of the CLI it dispatches and changes nothing else (case C29).
