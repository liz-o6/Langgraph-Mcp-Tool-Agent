"""Read-only browsing of the MCP workspace."""

from html import escape
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from integrations.filesystem import FILES_DIR

router = APIRouter(tags=["files"])


def workspace_path(relative: str) -> Path:
    root = FILES_DIR.resolve()
    try:
        candidate = (root / relative).resolve()
        candidate.relative_to(root)
    except (ValueError, OSError, RuntimeError):
        raise HTTPException(status_code=404, detail="File not found.") from None
    return candidate


@router.get("/files", response_class=HTMLResponse)
def browse_files(path: str = "") -> HTMLResponse:
    """Browse workspace directories and click to view or download files."""
    directory = workspace_path(path)
    if not directory.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found.")
    root = FILES_DIR.resolve()
    rows = []
    if directory != root:
        parent = quote(directory.parent.relative_to(root).as_posix(), safe="")
        rows.append(f'<li><a href="/files?path={parent}">../</a></li>')
    for entry in sorted(directory.iterdir(), key=lambda p: p.name.lower()):
        # Do not list symlinks, including links outside the workspace.
        if entry.is_symlink():
            continue
        relative = entry.relative_to(root).as_posix()
        label = escape(entry.name)
        if entry.is_dir():
            url = "/files?path=" + quote(relative, safe="")
            rows.append(f'<li><a href="{url}">{label}/</a></li>')
        elif entry.is_file():
            url = "/files/" + quote(relative, safe="/")
            rows.append(f'<li>{label} — <a href="{url}">查看 / View</a> · '
                        f'<a href="{url}?download=true">下载 / Download</a></li>')
    content = "\n".join(rows) or "<li>目录为空 / Empty directory</li>"
    return HTMLResponse(
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>Workspace files</title><body><h1>工作区文件 / Workspace files</h1>'
        f'<p>/{escape(directory.relative_to(root).as_posix())}</p><ul>{content}</ul>'
        '<p>文件存于当前服务实例；实例重启后可能丢失。</p></body></html>',
        headers={"Cache-Control": "no-store", "Content-Security-Policy": "default-src 'none'; base-uri 'none'"},
    )


@router.get("/files/{file_path:path}", response_class=FileResponse)
def read_file(file_path: str, download: bool = False) -> FileResponse:
    """View a file as plain text, or download it with download=true."""
    target = workspace_path(file_path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(
        target,
        media_type="application/octet-stream" if download else "text/plain",
        filename=target.name,
        content_disposition_type="attachment" if download else "inline",
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox; default-src 'none'",
        },
    )
