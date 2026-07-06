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


def test_render_episodes_injects_timeline(tmp_path, monkeypatch):
    import pandas as pd

    import pipeline.compute.episodes as epimod
    from pipeline import export

    monkeypatch.setattr(export.paths, "EPISODES", tmp_path / "episodes")
    monkeypatch.setattr(export.paths, "SITE", tmp_path / "site")
    (tmp_path / "episodes").mkdir()
    (tmp_path / "episodes" / "gfc.md").write_text("# GFC\n\nBody.\n")
    snaps = pd.DataFrame([
        {"episode": "gfc", "offset_months": -12, "indicator_id": "household_debt_gdp", "percentile": 95.0},
        {"episode": "gfc", "offset_months": -3, "indicator_id": "vix", "percentile": 88.0},
    ])
    monkeypatch.setattr(epimod, "load_snapshots", lambda: snaps)
    export.render_episodes()
    html = (tmp_path / "site" / "episodes" / "gfc.html").read_text()
    assert "Indicator timeline" in html
    assert "T−12m" in html or "T-12m" in html
    assert "household_debt_gdp" in html or "Household" in html
