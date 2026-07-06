import pandas as pd
import pytest

from pipeline import alerts, store
from pipeline.compute import sequencer
from pipeline.registry import Registry, Series

TH = {"regime_bands": [{"name": "cool", "upper": 40}, {"name": "warm", "upper": 70},
                        {"name": "frothy", "upper": 85}, {"name": "bubble_risk", "upper": 100}],
      "score_start": "1990-01-01",
      "alerts": {"pillar_extreme_level": 90, "cooldown_days": 7}}


def reg_one():
    return Registry(series=[Series("s1", "fred", "S1", "daily", 7, 0, 1)], indicators=[],
                    pillar_weights={"valuation": 1.0})


def write_scores(tmp_path, comp_rows, pillar_rows):
    (tmp_path).mkdir(parents=True, exist_ok=True)
    pd.DataFrame(comp_rows, columns=["date", "window", "score", "regime"]).to_csv(tmp_path / "composite.csv", index=False)
    pd.DataFrame(pillar_rows, columns=["date", "window", "pillar", "score"]).to_csv(tmp_path / "pillars.csv", index=False)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(alerts.paths, "DATA_SCORES", tmp_path / "scores")
    monkeypatch.setattr(store.paths, "DATA_STATE", tmp_path / "state")
    store.save_freshness({"s1": {"last_fetch": "x", "fetch_ok": True, "last_obs": "2026-07-03", "error": None}})
    return tmp_path / "scores"


def test_regime_change_and_pillar_cross(env):
    write_scores(env,
        [["2026-07-02", "full", 69.0, "warm"], ["2026-07-03", "full", 71.0, "frothy"]],
        [["2026-07-02", "full", "valuation", 89.0], ["2026-07-03", "full", "valuation", 91.0]])
    out = alerts.evaluate_alerts(reg_one(), TH, pd.Timestamp("2026-07-05"))
    labels = [a.label for a in out]
    assert "alert:regime" in labels
    assert "alert:pillar-valuation" in labels
    regime = next(a for a in out if a.label == "alert:regime")
    assert "warm" in regime.body and "frothy" in regime.title


def test_no_alerts_when_steady(env):
    write_scores(env,
        [["2026-07-02", "full", 50.0, "warm"], ["2026-07-03", "full", 51.0, "warm"]],
        [["2026-07-02", "full", "valuation", 50.0], ["2026-07-03", "full", "valuation", 51.0]])
    assert alerts.evaluate_alerts(reg_one(), TH, pd.Timestamp("2026-07-05")) == []


def test_stale_series_alert(env):
    write_scores(env,
        [["2026-07-03", "full", 50.0, "warm"]],
        [["2026-07-03", "full", "valuation", 50.0]])
    out = alerts.evaluate_alerts(reg_one(), TH, pd.Timestamp("2026-08-01"))  # s1 obs is 29d old, budget 7
    assert [a.label for a in out] == ["data-health"]
    assert "s1" in out[0].body


def reg_three():
    return Registry(series=[Series("s1", "fred", "S1", "daily", 7, 0, 1),
                            Series("s2", "fred", "S2", "daily", 7, 0, 1),
                            Series("s3", "fred", "S3", "daily", 7, 0, 1)],
                    indicators=[], pillar_weights={"valuation": 1.0})


def test_fetch_failure_rate_alert(env):
    write_scores(env,
        [["2026-07-03", "full", 50.0, "warm"]],
        [["2026-07-03", "full", "valuation", 50.0]])
    now = pd.Timestamp("2026-07-05")

    store.save_freshness({
        "s1": {"last_fetch": "x", "fetch_ok": True, "last_obs": "2026-07-04", "error": None},
        "s2": {"last_fetch": "x", "fetch_ok": False, "last_obs": "2026-07-04", "error": "boom"},
        "s3": {"last_fetch": "x", "fetch_ok": False, "last_obs": "2026-07-04", "error": "boom"},
    })
    out = alerts.evaluate_alerts(reg_three(), TH, now)
    assert [a.label for a in out] == ["data-health"]
    assert "s2" in out[0].body and "s3" in out[0].body

    store.save_freshness({
        "s1": {"last_fetch": "x", "fetch_ok": True, "last_obs": "2026-07-04", "error": None},
        "s2": {"last_fetch": "x", "fetch_ok": True, "last_obs": "2026-07-04", "error": None},
        "s3": {"last_fetch": "x", "fetch_ok": True, "last_obs": "2026-07-04", "error": None},
    })
    assert alerts.evaluate_alerts(reg_three(), TH, now) == []


def make_seq_state(as_of, stage_overrides):
    st = sequencer.new_state()
    st["as_of"] = as_of
    st["engaged"] = True
    st["current_stage"] = max(int(n) for n in stage_overrides)
    for n_str, overrides in stage_overrides.items():
        st["stages"][n_str].update(overrides)
    return st


def test_stage_alert_within_recency_window_emitted(env):
    # as_of is 3 days after fired_date (e.g. weekend/holiday slip in a local run) -> still delivered
    state = make_seq_state("2026-07-06", {
        "1": {"fired": True, "fired_date": "2026-07-03", "lapsed": False},
        "3": {"fired": True, "fired_date": "2026-07-03", "lapsed": False},
    })
    sequencer.save_state(state)
    out = alerts.evaluate_alerts(reg_one(), TH, pd.Timestamp("2026-07-06"))
    labels = [a.label for a in out]
    assert "alert:stage-1" in labels
    assert "alert:stage-3" in labels


def test_stage_alert_outside_recency_window_not_emitted(env):
    # as_of is 10 days after fired_date -> outside the bounded window, no alert
    store.save_freshness({"s1": {"last_fetch": "x", "fetch_ok": True, "last_obs": "2026-07-13", "error": None}})
    state = make_seq_state("2026-07-13", {
        "1": {"fired": True, "fired_date": "2026-07-03", "lapsed": False},
    })
    sequencer.save_state(state)
    out = alerts.evaluate_alerts(reg_one(), TH, pd.Timestamp("2026-07-13"))
    assert [a.label for a in out] == []


def test_stage_alert_lapsed_not_emitted(env):
    # recent fired_date but stage has since lapsed -> no alert
    state = make_seq_state("2026-07-06", {
        "1": {"fired": True, "fired_date": "2026-07-03", "lapsed": True},
    })
    sequencer.save_state(state)
    out = alerts.evaluate_alerts(reg_one(), TH, pd.Timestamp("2026-07-06"))
    assert [a.label for a in out] == []


def test_deliver_local_prints_not_calls_gh(env, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    called = []
    monkeypatch.setattr(alerts.subprocess, "run", lambda *a, **k: called.append(a))
    result = alerts.deliver([alerts.Alert("alert:regime", "t", "b")], 7)
    assert called == []
    assert result == 0
    assert "alert:regime" in capsys.readouterr().out


def test_deliver_ci_respects_cooldown(env, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    calls = []

    class R:
        def __init__(self, out, returncode=0, stderr=""):
            self.stdout = out
            self.returncode = returncode
            self.stderr = stderr

    def fake_run(cmd, capture_output=True, text=True, check=False):
        calls.append(cmd)
        if "list" in cmd:
            # first label: recent issue exists; second: none
            return R("[]" if "alert:pillar-valuation" in cmd else '[{"number": 5}]')
        return R("")

    monkeypatch.setattr(alerts.subprocess, "run", fake_run)
    result = alerts.deliver([alerts.Alert("alert:regime", "t1", "b1"),
                    alerts.Alert("alert:pillar-valuation", "t2", "b2")], 7)
    assert result == 0
    creates = [c for c in calls if "create" in c]
    assert len(creates) == 1
    assert "alert:pillar-valuation" in " ".join(creates[0])


def test_deliver_ci_fail_closed_on_list_error(env, monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    calls = []

    class R:
        def __init__(self, out, returncode=0, stderr=""):
            self.stdout = out
            self.returncode = returncode
            self.stderr = stderr

    def fake_run(cmd, capture_output=True, text=True, check=False):
        calls.append(cmd)
        if "list" in cmd:
            return R("", returncode=1, stderr="error")
        return R("")

    monkeypatch.setattr(alerts.subprocess, "run", fake_run)
    result = alerts.deliver([alerts.Alert("alert:regime", "t", "b")], 7)
    assert result == 0
    creates = [c for c in calls if "create" in c]
    assert len(creates) == 0
    assert "fail-closed" in capsys.readouterr().out


def test_deliver_ci_reports_create_failure(env, monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    calls = []

    class R:
        def __init__(self, out, returncode=0, stderr=""):
            self.stdout = out
            self.returncode = returncode
            self.stderr = stderr

    def fake_run(cmd, capture_output=True, text=True, check=False):
        calls.append(cmd)
        if "list" in cmd:
            return R("[]", returncode=0)
        if "create" in cmd:
            return R("", returncode=1, stderr="boom")
        return R("")

    monkeypatch.setattr(alerts.subprocess, "run", fake_run)
    result = alerts.deliver([alerts.Alert("alert:regime", "t", "b")], 7)
    assert result == 1
    assert "FAILED" in capsys.readouterr().out
