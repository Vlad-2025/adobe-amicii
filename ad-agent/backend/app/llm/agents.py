"""The four LLM call sites. Each has a deterministic template fallback so the demo runs with no LLM."""
from __future__ import annotations

import json
import logging
import zlib
from pathlib import Path

import numpy as np

from app import db
from app.config import SEED
from app.llm import guard, provider
from app.llm.schemas import (LEARNING_SCHEMA, NARRATIVE_SCHEMA, PERSONA_SCHEMA, VARIANTS_SCHEMA, Learning, Narrative,
                             Persona, Variants)
from app.world.embed import creative_text, get_embedder

log = logging.getLogger(__name__)
PROMPTS = Path(__file__).parent / "prompts"


def _prompt(name: str) -> str:
    b = guard.brand()
    brand_line = (f"Brand: {b['name']}, {b['product']}, €{b['price_eur']:.2f}/can, target {b['target_age']}. Tone: {b['tone']}. "
                  f"Banned: {', '.join(b['banned_phrases'])}; no health claims; never name competitors.")
    return (PROMPTS / f"{name}.txt").read_text(encoding="utf-8") + "\n" + brand_line


# ---------------- community profiler ----------------
def _hours_window(hours: list[float]) -> str:
    h = np.array(hours)
    best = max(range(24), key=lambda s: sum(h[(s + i) % 24] for i in range(4)))
    return f"{best:02d}:00-{(best + 4) % 24:02d}:00 UTC"


def profile_community(c: dict) -> tuple[dict, str]:
    kws = json.loads(c["keywords"]) if isinstance(c["keywords"], str) else c["keywords"]
    posts = json.loads(c["central_posts"]) if isinstance(c["central_posts"], str) else c["central_posts"]
    hours = json.loads(c["hours"]) if isinstance(c["hours"], str) else c["hours"]
    top_h = sorted(range(24), key=lambda i: -hours[i])[:6]
    inputs = {"size": c["size"], "keywords": kws[:15], "central_posts": posts[:5], "top_hours_utc": {f"{i:02d}h": round(hours[i], 3) for i in top_h}}

    def fallback():
        pack = c.get("dominant_pack")
        name = (pack.replace("_", " ").title() if pack and pack != "unknown" else " & ".join(k.title() for k in kws[:2])) + " crowd"
        return {"name": name[:60], "one_liner": f"{c['size']} accounts posting about {', '.join(kws[:4])}.",
                "interests": kws[:4] or ["general"], "tone": "casual", "do": [f"Reference {kws[0] if kws else 'their interests'} directly"],
                "dont": ["Generic lifestyle claims"], "best_hours": _hours_window(hours)}

    return provider.generate("community_profile", _prompt("profiler"), inputs, PERSONA_SCHEMA, Persona, 0.3, fallback)


def profile_all_communities() -> None:
    for c in db.q("SELECT * FROM communities ORDER BY community_id"):
        persona, src = profile_community(c)
        persona["source"] = src
        db.x("UPDATE communities SET persona=? WHERE community_id=?", (json.dumps(persona, ensure_ascii=False), c["community_id"]))


def community_names() -> dict[int, str]:
    out = {}
    for r in db.q("SELECT community_id, persona, keywords FROM communities"):
        p = json.loads(r["persona"]) if r["persona"] else None
        kws = json.loads(r["keywords"])
        out[r["community_id"]] = p["name"] if p else " & ".join(k.title() for k in kws[:2])
    return out


# ---------------- root-cause narrator ----------------
PRETTY = {"creative_fatigue": "creative fatigue", "segment_saturation": "segment saturation", "auction_pressure": "auction cost pressure",
          "landing_page": "a landing page / funnel problem", "seasonality": "a market-wide seasonal dip", "tracking": "broken conversion tracking",
          "no_issue": "normal noise"}
ACTION_TEXT = {"refresh_creative": "Generate new variants that change one dimension and test them against the original.",
               "split_by_segment": "Keep the ad where it still works and replace it in the saturated community.",
               "rebalance_budget": "Move budget to ad sets with headroom until auction prices settle.",
               "fix_landing_page": "Check the landing page and checkout; hold back budget until conversion recovers.",
               "do_nothing": "Do nothing: the drop is market-wide and should recover on its own.",
               "check_tracking": "Check the pixel / conversion API before changing any budget."}


def narrate(diag: dict, ad: dict) -> tuple[dict, str]:
    probs = {k: round(v, 3) for k, v in sorted(diag["probabilities"].items(), key=lambda x: -x[1]) if v >= 0.01}
    ev = [{"evidence": e["label"], "value": e["value"]} for e in diag["evidence"][:4]]
    inputs = {"ad": {"id": ad["ad_id"], "hook": ad.get("hook"), "angle": ad.get("angle")}, "probabilities": probs, "top_evidence": ev,
              "recommended_action_type": diag["recommended_action"]}

    def fallback():
        top = diag["top"]
        p = diag["probabilities"][top]
        second = sorted(diag["probabilities"].items(), key=lambda x: -x[1])[1]
        e1 = diag["evidence"][0]
        return {"headline": f"{ad['ad_id']}: most likely {PRETTY[top]} ({p:.0%})",
                "explanation": (f"The strongest signal is {e1['label'].lower()} at {e1['value']}. "
                                f"The next most likely cause, {PRETTY[second[0]]}, is at {second[1]:.0%}."),
                "recommended_action": ACTION_TEXT[diag["recommended_action"]]}

    return provider.generate("narrate", _prompt("narrator"), inputs, NARRATIVE_SCHEMA, Narrative, 0.3, fallback)


# ---------------- memory ----------------
def retrieve_memory(query: str, pack: str | None, k: int = 3) -> list[dict]:
    rows = db.q("SELECT * FROM memory")
    if not rows:
        return []
    q = get_embedder().embed([query])[0]
    scored = []
    for r in rows:
        e = db.unblob(r["embedding"])
        scored.append((float(e @ q) if e is not None else 0.0, r))
    scored.sort(key=lambda x: -x[0])
    picked = [r for _, r in scored[:k]]
    for _, r in scored:
        a = json.loads(r["applies_to"])
        if not r["winner"] and pack and a.get("pack") in (pack, "*") and r not in picked:
            picked.append(r)
    return [{"id": r["id"], "insight": r["insight"], "evidence": r["evidence"], "applies_to": json.loads(r["applies_to"]), "winner": bool(r["winner"])} for r in picked]


# ---------------- creative strategist ----------------
def _bank() -> dict:
    return json.loads((SEED / "variant_bank.json").read_text(encoding="utf-8"))


def generate_variants(ad: dict, diag: dict | None, persona: dict, keywords: list[str], memory: list[dict], extra_note: str | None = None) -> tuple[list[dict], str]:
    original = {k: ad.get(k) for k in ("hook", "body", "cta", "offer", "tone", "angle")}
    losing_dims = {m["applies_to"].get("dimension") for m in memory if not m["winner"]}
    inputs = {"original": original, "diagnosis": diag["top"] if diag else "creative_fatigue",
              "target_community": {"name": persona.get("name"), "one_liner": persona.get("one_liner"), "tone": persona.get("tone"),
                                   "do": persona.get("do"), "dont": persona.get("dont"), "keywords": keywords[:10]},
              "memory": [{"insight": m["insight"], "winner": m["winner"]} for m in memory]}
    if extra_note:
        inputs["note"] = extra_note

    def fallback():
        bank = _bank()
        order = [d for d in ["emotional_angle", "hook", "benefit", "cta", "offer"] if d not in losing_dims]
        out = []
        for dim in order[:3]:
            opt = bank[dim][zlib.crc32((ad["ad_id"] + dim).encode()) % len(bank[dim])]
            v = {"changed_dimension": dim, "hook": original["hook"], "body": original["body"], "cta": original["cta"], "offer": original["offer"] or "none"}
            v.update({k: opt[k] for k in ("hook", "body", "cta", "offer") if k in opt})
            v["hypothesis"] = opt["hypothesis"]
            v["expected_effect"] = "CTR up vs the original" if dim != "offer" else "Conversion rate up, CTR flat"
            out.append(v)
        return {"variants": out}

    data, src = provider.generate("variants", _prompt("strategist"), inputs, VARIANTS_SCHEMA, Variants, 0.8, fallback)
    variants = data["variants"][:3]
    # code-side checks: one distinct dimension each, not a cosmetic rewrite of the original
    emb = get_embedder()
    orig_vec = emb.embed([creative_text(original)])[0]
    seen, ok = set(), []
    for v in variants:
        vec = emb.embed([creative_text(v)])[0]
        sim = float(vec @ orig_vec)
        if v["changed_dimension"] in seen or sim > 0.92:
            continue
        seen.add(v["changed_dimension"])
        v["similarity_to_original"] = round(sim, 3)
        v["emb"] = vec
        v["guard"] = guard.check(v)
        ok.append(v)
    if len(ok) < 3 and extra_note is None and src not in ("template", "cache"):
        return generate_variants(ad, diag, persona, keywords, memory,
                                 extra_note="Previous answer repeated a dimension or was too close to the original. Use 3 different dimensions and change them substantially.")
    if len(ok) < 2:  # last resort: template variants
        fb = fallback()["variants"]
        for v in fb:
            if v["changed_dimension"] not in seen:
                vec = emb.embed([creative_text(v)])[0]
                v.update({"similarity_to_original": round(float(vec @ orig_vec), 3), "emb": vec, "guard": guard.check(v)})
                ok.append(v)
                seen.add(v["changed_dimension"])
        src = src + "+template"
    return ok[:3], src


# ---------------- learning writer ----------------
def write_learning(exp_summary: dict, community_name: str, pack: str | None, day: int) -> tuple[dict, str]:
    def fallback():
        w = exp_summary["winner_arm"]
        base = exp_summary["arms"][0]
        if w["ad_id"] == base["ad_id"]:
            ins = f"For {community_name}, none of the tested changes beat the original {exp_summary['metric']}."
        else:
            ins = f"For {community_name}, changing the {w['changed_dimension'].replace('_', ' ')} beat the original on {exp_summary['metric']}."
        return {"insight": ins, "evidence": f"{w['ad_id']} {w['rate']:.2%} vs original {base['rate']:.2%}, P(best) {w['p_best']:.0%}",
                "community": community_name, "dimension": w.get("changed_dimension") or "none"}

    data, src = provider.generate("learning", _prompt("learning"), exp_summary, LEARNING_SCHEMA, Learning, 0.3, fallback)
    vec = get_embedder().embed([data["insight"]])[0]
    winner_is_variant = exp_summary["winner_arm"]["ad_id"] != exp_summary["arms"][0]["ad_id"]
    mid = db.x("INSERT INTO memory(brand,insight,evidence,applies_to,winner,embedding,created_day) VALUES (?,?,?,?,?,?,?)",
               ("Volt", data["insight"], data["evidence"], json.dumps({"pack": pack, "community": data["community"], "dimension": data["dimension"]}),
                int(winner_is_variant), db.blob(vec), day))
    data["id"] = mid
    return data, src
