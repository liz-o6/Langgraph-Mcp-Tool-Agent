from fastapi.testclient import TestClient
from app.main import create_app
from app.api.routes import files


def test_browse_view_download_and_boundary(tmp_path, monkeypatch):
    root = tmp_path / 'workspace'
    outputs = root / 'outputs'
    outputs.mkdir(parents=True)
    (outputs / 'demo.txt').write_text('grading-83721')
    (outputs / '<script>.html').write_text('<script>alert(1)</script>')
    secret = tmp_path / 'private.txt'
    secret.write_text('must not leak')
    (outputs / 'escape.txt').symlink_to(secret)
    monkeypatch.setattr(files, 'FILES_DIR', root)
    client = TestClient(create_app())
    listing = client.get('/files?path=outputs')
    assert listing.status_code == 200
    assert '/files/outputs/demo.txt?download=true' in listing.text
    assert '&lt;script&gt;.html' in listing.text
    assert 'escape.txt' not in listing.text
    viewed = client.get('/files/outputs/demo.txt')
    assert viewed.text == 'grading-83721'
    assert viewed.headers['content-type'].startswith('text/plain')
    assert viewed.headers['content-disposition'].startswith('inline')
    downloaded = client.get('/files/outputs/demo.txt?download=true')
    assert downloaded.content == b'grading-83721'
    assert downloaded.headers['content-disposition'].startswith('attachment')
    for url in ['/files/%2e%2e/private.txt', '/files/outputs/escape.txt',
                '/files?path=../', '/files?path=/etc', '/files/missing', '/files/outputs']:
        assert client.get(url).status_code == 404
