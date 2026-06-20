"""FastAPI web application for the dive-log DSSG analyzer.

A user uploads a dive-log export (UDDF or Subsurface XML); the file is stored
permanently on the server, analysed **server-side** for the DAN Surface
Supersaturation Gradient of every dive, and the generated report can be browsed
in the browser. A small JSON API exposes the same analysis.

Run with::

    uvicorn dssg.web:app --reload
    # or: python serve.py

Security notes (untrusted uploads):
* XML is parsed with DTD/entity declarations disabled (no billion-laughs/XXE).
* Upload size is capped (``MAX_UPLOAD_BYTES``).
* Report/download paths are validated against directory traversal.
* Stored filenames are sanitised; files live under a random per-upload id.
"""

from __future__ import annotations

import html
import os

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

from .parser import SUPPORTED_FORMATS
from .report import CSS
from .store import MAX_UPLOAD_BYTES, DiveStore

DATA_DIR = os.environ.get("DSSG_DATA_DIR", "data")
store = DiveStore(DATA_DIR)

app = FastAPI(
    title="vino — dive-log DSSG analyzer",
    description="Compute the DAN Surface Supersaturation Gradient from dive-log "
                "exports. Non-commercial use only (AGPL-3.0 + Commons Clause).",
    version="1.0.0",
)

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".json": "application/json",
    ".csv": "text/csv",
}


# --------------------------------------------------------------------------- #
# HTML rendering
# --------------------------------------------------------------------------- #

def _page(title: str, body: str) -> str:
    return (
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{html.escape(title)}</title><style>{CSS}"
        ".drop{border:2px dashed var(--line);border-radius:12px;padding:28px;"
        "text-align:center;background:var(--panel)}"
        "input[type=file]{color:var(--ink)}"
        "button{background:var(--accent);color:#04222e;border:0;border-radius:8px;"
        "padding:10px 18px;font-size:15px;font-weight:600;cursor:pointer;margin-top:12px}"
        "</style></head><body><div class='wrap'>" + body +
        "<footer>vino &middot; DAN Surface Supersaturation Gradient analyzer "
        "&middot; non-commercial use only (AGPL-3.0 + Commons Clause)</footer>"
        "</div></body></html>"
    )


def landing_page(message: str = "", error: str = "") -> str:
    formats = "".join(f"<li>{html.escape(f)}</li>" for f in SUPPORTED_FORMATS)
    banner = ""
    if message:
        banner += (f"<div class='panel' style='border-color:var(--good)'>"
                   f"{html.escape(message)}</div>")
    if error:
        banner += (f"<div class='panel' style='border-color:var(--bad)'>"
                   f"<b>Upload problem:</b> {html.escape(error)}</div>")

    rows = []
    for e in store.entries():
        when = html.escape(e.get("uploaded_at", "")[:19].replace("T", " "))
        name = html.escape(e.get("filename", ""))
        if e.get("status") == "ok":
            mean = e.get("mean_dssg")
            mean_s = f"{mean:.2f}" if isinstance(mean, (int, float)) else "—"
            rows.append(
                f"<tr><td>{when}</td>"
                f"<td><a href='/report/{e['id']}/'>{name}</a></td>"
                f"<td>{html.escape(str(e.get('format', '')))}</td>"
                f"<td class='num'>{e.get('dive_count', 0)}</td>"
                f"<td class='num'>{mean_s}</td>"
                f"<td><a href='/download/{e['id']}'>raw</a></td></tr>"
            )
        else:
            rows.append(
                f"<tr><td>{when}</td><td>{name}</td>"
                f"<td colspan='3' class='muted'>error: "
                f"{html.escape(str(e.get('error', '')))}</td>"
                f"<td><a href='/download/{e['id']}'>raw</a></td></tr>"
            )
    history = (
        "<div class='panel'><h2>Previous analyses</h2><table><thead><tr>"
        "<th>Uploaded</th><th>File</th><th>Format</th><th class='num'>Dives</th>"
        "<th class='num'>Mean DSSG</th><th>Original</th></tr></thead><tbody>"
        + ("".join(rows) or "<tr><td colspan='6' class='muted'>"
           "No uploads yet.</td></tr>")
        + "</tbody></table></div>"
    )

    body = (
        "<header><h1>Dive-log DSSG analyzer</h1>"
        "<div class='sub'>Upload a dive-log export to compute the DAN Surface "
        "Supersaturation Gradient for every dive &mdash; analysed on the "
        "server.</div></header>"
        + banner +
        "<div class='panel'><h2>Upload a dive log</h2>"
        "<form class='drop' method='post' action='/upload' "
        "enctype='multipart/form-data'>"
        "<p class='muted'>Choose a UDDF or Subsurface XML export</p>"
        "<input type='file' name='file' required accept='.uddf,.xml,.ssrf'><br>"
        "<button type='submit'>Analyze &amp; store</button></form>"
        "<p class='muted' style='margin-top:14px'>Supported formats — any app "
        "that exports a per-dive depth/time profile and gas mix:</p>"
        f"<ul class='muted'>{formats}</ul></div>"
        + history +
        "<div class='panel method'><p>Uploaded files are stored permanently on "
        "the server. A JSON API is available at <code>/api/analyses</code> and "
        "<code>/api/analyses/{id}</code>. This is an educational tool, not a "
        "dive planner or medical device.</p></div>"
    )
    return _page("Dive-log DSSG analyzer", body)


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #

@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse(landing_page())


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        limit = MAX_UPLOAD_BYTES // (1024 * 1024)
        return HTMLResponse(
            landing_page(error=f"file exceeds the {limit} MB limit"),
            status_code=413)
    if not data or not file.filename:
        return HTMLResponse(landing_page(error="no file was uploaded"),
                            status_code=400)

    entry = store.add(file.filename, data)
    if entry.get("status") == "ok":
        return RedirectResponse(f"/report/{entry['id']}/", status_code=303)
    return HTMLResponse(
        landing_page(error=f"\"{html.escape(file.filename)}\" was stored but "
                     f"could not be analysed: {entry.get('error', '')}"),
        status_code=200)


@app.get("/report/{uid}", include_in_schema=False)
def report_root_noslash(uid: str) -> RedirectResponse:
    return RedirectResponse(f"/report/{uid}/", status_code=308)


@app.get("/report/{uid}/{path:path}")
def report(uid: str, path: str = ""):
    target = store.report_file(uid, path or "index.html")
    if not target:
        raise HTTPException(status_code=404, detail="report not found")
    ext = os.path.splitext(target)[1]
    return FileResponse(target,
                        media_type=_CONTENT_TYPES.get(ext, "application/octet-stream"))


@app.get("/download/{uid}")
def download(uid: str):
    target = store.original_file(uid)
    if not target:
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(target, filename=os.path.basename(target),
                        media_type="application/octet-stream")


@app.get("/api/analyses")
def api_analyses() -> JSONResponse:
    return JSONResponse(store.entries())


@app.get("/api/analyses/{uid}")
def api_analysis(uid: str) -> JSONResponse:
    entry = store.entry(uid)
    if not entry:
        raise HTTPException(status_code=404, detail="analysis not found")
    result = dict(entry)
    stats = store.statistics(uid)
    if stats is not None:
        result["statistics"] = stats
    return JSONResponse(result)
