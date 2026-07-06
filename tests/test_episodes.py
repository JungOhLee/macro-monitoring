from pipeline import export


def test_render_episodes(tmp_path, monkeypatch):
    monkeypatch.setattr(export.paths, "EPISODES", tmp_path / "episodes")
    monkeypatch.setattr(export.paths, "SITE", tmp_path / "site")
    (tmp_path / "episodes").mkdir()
    (tmp_path / "episodes" / "demo.md").write_text("# Demo Crisis\n\nBody **bold**.\n")
    names = export.render_episodes()
    assert names == ["demo"]
    html = (tmp_path / "site" / "episodes" / "demo.html").read_text()
    assert "<h1>Demo Crisis</h1>" in html
    assert "<strong>bold</strong>" in html
    assert "../assets/style.css" in html
