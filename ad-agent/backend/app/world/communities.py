"""Community detection: Leiden (igraph + leidenalg) with a pure-Python Louvain fallback,
then per-community keywords (class-based TF-IDF), central posts and active hours."""
from __future__ import annotations

import logging
from collections import Counter

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.metrics import normalized_mutual_info_score

log = logging.getLogger(__name__)

MIN_SIZE = 50


def _edges(accounts: pd.DataFrame, follows: pd.DataFrame, interactions: pd.DataFrame):
    index = {u: i for i, u in enumerate(accounts["user_id"])}
    w: Counter = Counter()
    for df, weight in ((follows, 1.0), (interactions, 2.0)):
        s = df["src"].map(index)
        d = df["dst"].map(index)
        ok = s.notna() & d.notna()
        for a, b, x in zip(s[ok].astype(int), d[ok].astype(int), df.loc[ok, "weight"].astype(float)):
            if a == b:
                continue
            key = (a, b) if a < b else (b, a)
            w[key] += weight * (x if weight == 2.0 else 1.0)
    return len(index), w


def _leiden(n: int, w: Counter, seed: int) -> np.ndarray | None:
    try:
        import igraph as ig
        import leidenalg
    except Exception as e:
        log.warning("leidenalg unavailable (%s); falling back to networkx Louvain", type(e).__name__)
        return None
    g = ig.Graph(n=n, edges=list(w.keys()))
    g.es["weight"] = list(w.values())
    best = None
    for res in (0.6, 0.8, 1.0, 1.2, 1.5, 2.0):
        part = leidenalg.find_partition(
            g, leidenalg.RBConfigurationVertexPartition, weights="weight", resolution_parameter=res, seed=seed
        )
        labels = np.array(part.membership)
        big = int(np.sum(np.bincount(labels) >= MIN_SIZE))
        if 6 <= big <= 10:
            return labels
        if best is None or abs(big - 8) < abs(best[0] - 8):
            best = (big, labels)
    return best[1]


def _louvain(n: int, w: Counter, seed: int) -> np.ndarray:
    import networkx as nx

    g = nx.Graph()
    g.add_nodes_from(range(n))
    g.add_weighted_edges_from((a, b, x) for (a, b), x in w.items())
    best = None
    for res in (0.6, 0.8, 1.0, 1.2, 1.5):
        comms = nx.community.louvain_communities(g, weight="weight", resolution=res, seed=seed)
        labels = np.zeros(n, int)
        for i, c in enumerate(comms):
            labels[list(c)] = i
        big = int(np.sum(np.bincount(labels) >= MIN_SIZE))
        if 6 <= big <= 10:
            return labels
        if best is None or abs(big - 8) < abs(best[0] - 8):
            best = (big, labels)
    return best[1]


def _merge_small(labels: np.ndarray, interest: np.ndarray) -> np.ndarray:
    labels = labels.copy()
    counts = np.bincount(labels)
    big = [c for c in range(len(counts)) if counts[c] >= MIN_SIZE]
    if not big:
        return np.zeros_like(labels)
    cents = np.stack([interest[labels == c].mean(0) for c in big])
    cents /= np.linalg.norm(cents, axis=1, keepdims=True) + 1e-8
    for c in range(len(counts)):
        if counts[c] and c not in big:
            idx = labels == c
            v = interest[idx].mean(0)
            labels[idx] = big[int(np.argmax(cents @ v))]
    # relabel 0..k-1 by size, largest first
    order = [c for c, _ in Counter(labels).most_common()]
    remap = {c: i for i, c in enumerate(order)}
    return np.array([remap[c] for c in labels])


def detect(accounts: pd.DataFrame, follows: pd.DataFrame, interactions: pd.DataFrame, interest: np.ndarray, seed: int = 7):
    n, w = _edges(accounts, follows, interactions)
    labels = _leiden(n, w, seed)
    method = "leiden"
    if labels is None:
        labels = _louvain(n, w, seed)
        method = "louvain"
    labels = _merge_small(labels, interest)
    nmi = None
    if "source_pack" in accounts:
        nmi = float(normalized_mutual_info_score(accounts["source_pack"], labels))
    return labels, method, nmi


STOP_EXTRA = {"lol", "just", "today", "new", "anyone", "else", "right", "now", "really", "time", "day", "got", "im", "dont", "amp", "https", "com", "www"}


def describe(accounts: pd.DataFrame, posts: pd.DataFrame, labels: np.ndarray, post_emb: np.ndarray, interest: np.ndarray):
    """Per community: size, top keywords (c-TF-IDF), 5 central posts, hour histogram, centroid, dominant seed pack."""
    lab_of_user = dict(zip(accounts["user_id"], labels))
    plab = posts["user_id"].map(lab_of_user).to_numpy()
    k = int(labels.max()) + 1
    docs = [" ".join(posts["text"][plab == c].tolist()) for c in range(k)]
    cv = CountVectorizer(stop_words="english", min_df=1, max_features=20000, token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z\-]{2,}\b")
    X = cv.fit_transform(docs).astype(float).toarray()
    tf = X / np.maximum(X.sum(1, keepdims=True), 1)
    avg = X.sum() / k
    idf = np.log(1 + avg / np.maximum(X.sum(0), 1))
    ctfidf = tf * idf
    vocab = np.array(cv.get_feature_names_out())
    hours = pd.to_datetime(posts["ts"], utc=True).dt.hour.to_numpy()
    out = []
    for c in range(k):
        members = labels == c
        cent = interest[members].mean(0)
        cent = cent / (np.linalg.norm(cent) + 1e-8)
        order = np.argsort(-ctfidf[c])
        kws = [w for w in vocab[order] if w not in STOP_EXTRA][:15]
        pidx = np.flatnonzero(plab == c)
        central = []
        if len(pidx):
            sims = post_emb[pidx] @ cent
            seen = set()
            for j in pidx[np.argsort(-sims)]:
                t = posts["text"].iat[j]
                if t not in seen:
                    seen.add(t)
                    central.append(t)
                if len(central) == 5:
                    break
        hist = np.bincount(hours[pidx], minlength=24).astype(float) if len(pidx) else np.zeros(24)
        hist = hist / max(hist.sum(), 1)
        packs = accounts.loc[members, "source_pack"].value_counts() if "source_pack" in accounts else pd.Series(dtype=int)
        out.append({
            "community_id": c,
            "size": int(members.sum()),
            "keywords": kws,
            "central_posts": central,
            "hours": hist.round(4).tolist(),
            "centroid": cent.astype(np.float32),
            "dominant_pack": str(packs.index[0]) if len(packs) else None,
            "pack_share": {str(p): round(int(v) / int(members.sum()), 3) for p, v in packs.items()},
        })
    return out
