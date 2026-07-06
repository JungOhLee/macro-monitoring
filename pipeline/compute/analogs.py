from __future__ import annotations

import math

import pandas as pd


def cosine(a: dict[str, float], b: dict[str, float], min_shared: int = 8) -> float | None:
    shared = sorted(set(a) & set(b))
    if len(shared) < min_shared:
        return None
    # Percentiles are all-positive (0-100), which floors raw cosine similarity near
    # ~0.70-1.0 regardless of how dissimilar two profiles actually are (any two vectors
    # of positive numbers point into the same orthant). Demean on 50 (the neutral
    # percentile) before the dot/norm so similarity actually spans the full [-1, 1]
    # range and can discriminate "opposite of today" from "just like today."
    va = [a[k] - 50.0 for k in shared]
    vb = [b[k] - 50.0 for k in shared]
    dot = sum(x * y for x, y in zip(va, vb))
    na = math.sqrt(sum(x * x for x in va))
    nb = math.sqrt(sum(y * y for y in vb))
    if na == 0 or nb == 0:
        return None
    return dot / (na * nb)


def top_analogs(today: dict[str, float], snaps: pd.DataFrame, k: int = 3) -> list[dict]:
    out = []
    pre = snaps[snaps.offset_months <= 0]
    for (ep, off), grp in pre.groupby(["episode", "offset_months"]):
        vec = dict(zip(grp.indicator_id, grp.percentile))
        sim = cosine(today, vec)
        if sim is None:
            continue
        shared = set(today) & set(vec)
        # Cosine similarity is scale-invariant, so proportional (but non-identical)
        # vectors can tie at 1.0. Break ties with Euclidean distance on shared keys
        # so the closer (more literal) match ranks first.
        dist = sum((today[key] - vec[key]) ** 2 for key in shared)
        out.append({"episode": ep, "offset_months": int(off),
                    "similarity": round(sim, 4), "n_shared": len(shared), "_dist": dist})
    ranked = sorted(out, key=lambda d: (-d["similarity"], d["_dist"]))[:k]
    for d in ranked:
        d.pop("_dist")
    return ranked
