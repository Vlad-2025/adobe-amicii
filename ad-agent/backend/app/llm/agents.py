"""The four LLM call sites. Each has a deterministic template fallback so the demo runs with no LLM.
Everything is per company (brand kit, memory, variant bank) and per channel (communities)."""
from __future__ import annotations

import json
import logging
import zlib
from pathlib import Path

import numpy as np

from app import db, registry
from app.llm import guard, provider
from app.llm.schemas import (LEARNING_SCHEMA, NARRATIVE_SCHEMA, PERSONA_SCHEMA, VARIANTS_SCHEMA, Learning, Narrative,
                             Persona, Variants)
from app.world.embed import creative_text, get_embedder

log = logging.getLogger(__name__)
PROMPTS = Path(__file__).parent / "prompts"


def _prompt(name: str, b: dict, platform: str | None = None) -> str:
    brand_line = (f"Brand: {b['name']}, {b['product']}, typical price €{b['price_eur']}, target {b['target_age']}. Tone: {b['tone']}. "
                  f"Banned: {', '.join(b['banned_phrases']) or 'none'}; no health claims; never name competitors ({', '.join(b['competitors']) or 'none'}).")
    if platform:
        brand_line += f" Channel: {platform}."
    return (PROMPTS / f"{name}.txt").read_text(encoding="utf-8") + "\n" + brand_line


# ---------------- community profiler ----------------
def _hours_window(hours: list[float]) -> str:
    h = np.array(hours)
    best = max(range(24), key=lambda s: sum(h[(s + i) % 24] for i in range(4)))
    return f"{best:02d}:00-{(best + 4) % 24:02d}:00 UTC"


def profile_community(c: dict, b: dict, aud_type: str) -> tuple[dict, str]:
    kws = json.loads(c["keywords"]) if isinstance(c["keywords"], str) else c["keywords"]
    posts = json.loads(c["central_posts"]) if isinstance(c["central_posts"], str) else c["central_posts"]
    hours = json.loads(c["hours"]) if isinstance(c["hours"], str) else c["hours"]
    top_h = sorted(range(24), key=lambda i: -hours[i])[:6]
    inputs = {"size": c["size"], "keywords": kws[:15], "central_posts": posts[:5], "top_hours_utc": {f"{i:02d}h": round(hours[i], 3) for i in top_h}}
    if c.get("label"):
        inputs["platform_segment_definition"] = c["label"]

    def fallback():
        pack = c.get("dominant_pack")
        if pack and pack != "unknown":
            name = pack.replace("_", " ").title() + " crowd"
        else:
            name = " & ".join(k.title() for k in kws[:2]) + " crowd"
        return {"name": name[:60], "one_liner": f"{c['size']} {'people modeled from this segment' if aud_type == 'segments' else 'accounts'} talking about {', '.join(kws[:4])}.",
                "interests": kws[:4] or ["general"], "tone": "casual", "do": [f"Reference {kws[0] if kws else 'their interests'} directly"],
                "dont": ["Generic lifestyle claims"], "best_hours": _hours_window(hours)}

    return provider.generate("community_profile", _prompt("profiler", b), inputs, PERSONA_SCHEMA, Persona, 0.3, fallback)


def profile_all_communities(ch: str) -> None:
    chrow = registry.channel(ch)
    b = registry.brand_of(ch)
    aud_type = chrow["config"]["audience"]["type"]
    for c in db.q("SELECT * FROM communities WHERE channel_id=? ORDER BY community_id", (ch,)):
        persona, src = profile_community(c, b, aud_type)
        persona["source"] = src
        db.x("UPDATE communities SET persona=? WHERE channel_id=? AND community_id=?", (json.dumps(persona, ensure_ascii=False), ch, c["community_id"]))


def community_names(ch: str) -> dict[int, str]:
    out = {}
    for r in db.q("SELECT community_id, persona, keywords, label FROM communities WHERE channel_id=?", (ch,)):
        p = json.loads(r["persona"]) if r["persona"] else None
        kws = json.loads(r["keywords"])
        out[r["community_id"]] = p["name"] if p else (r["label"] or " & ".join(k.title() for k in kws[:2]))
    return out


# ---------------- root-cause narrator ----------------
PRETTY = {"creative_fatigue": "creative fatigue", "segment_saturation": "segment saturation", "auction_pressure": "auction cost pressure",
          "landing_page": "a landing page / funnel problem", "seasonality": "a market-wide seasonal dip", "tracking": "broken conversion tracking",
          "no_issue": "normal noise"}
ACTION_TEXT = {"refresh_creative": "Generate new variants that change one dimension and test them against the original.",
               "split_by_segment": "Keep the ad where it still works and replace it in the saturated segment.",
               "rebalance_budget": "Move budget to ad sets with headroom until auction prices settle.",
               "fix_landing_page": "Check the landing page and checkout or signup flow; hold back budget until conversion recovers.",
               "do_nothing": "Do nothing: the drop is market-wide and should recover on its own.",
               "check_tracking": "Check the pixel / conversion API before changing any budget."}


def narrate(diag: dict, ad: dict, b: dict) -> tuple[dict, str]:
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

    return provider.generate("narrate", _prompt("narrator", b), inputs, NARRATIVE_SCHEMA, Narrative, 0.3, fallback)


# ---------------- memory ----------------
def retrieve_memory(company_id: str, query: str, pack: str | None, k: int = 3) -> list[dict]:
    rows = db.q("SELECT * FROM memory WHERE company_id=?", (company_id,))
    if not rows:
        return []
    q = get_embedder().embed([query])[0]
    scored = sorted(((float(db.unblob(r["embedding"]) @ q), r) for r in rows), key=lambda x: -x[0])
    picked = [r for _, r in scored[:k]]
    for _, r in scored:
        a = json.loads(r["applies_to"])
        if not r["winner"] and pack and a.get("pack") in (pack, "*") and r not in picked:
            picked.append(r)
    return [{"id": r["id"], "insight": r["insight"], "evidence": r["evidence"], "applies_to": json.loads(r["applies_to"]), "winner": bool(r["winner"])} for r in picked]


# ---------------- creative strategist ----------------
def _generic_bank(b: dict) -> dict:
    p = b["product"]
    return {
        "hook": [{"hook": f"The {b['name']} way: less hassle, more done.", "hypothesis": "A fresh first line resets attention."}],
        "cta": [{"cta": "Learn more", "hypothesis": "A softer CTA lowers commitment."}],
        "benefit": [{"body": f"{p} that saves you time every week. See how in 30 seconds.", "hypothesis": "Time saved is a concrete benefit."}],
        "emotional_angle": [{"hook": "You deserve an easier week.", "body": f"{b['name']}: {p}, built so you can focus on what you enjoy.", "hypothesis": "Relief angle differs from a feature angle."}],
        "offer": [{"offer": "free trial", "hypothesis": "Removes the risk of trying."}],
    }


def generate_variants(ad: dict, diag: dict | None, persona: dict, keywords: list[str], memory: list[dict], company_cfg: dict,
                      platform: str, extra_note: str | None = None) -> tuple[list[dict], str]:
    b = company_cfg["brand"]
    bank = company_cfg.get("variant_bank") or {}
    generic = _generic_bank(b)
    bank = {k: bank.get(k) or generic[k] for k in generic}
    original = {k: ad.get(k) for k in ("hook", "body", "cta", "offer", "tone", "angle")}
    losing_dims = {m["applies_to"].get("dimension") for m in memory if not m["winner"]}
    inputs = {"original": original, "diagnosis": diag["top"] if diag else "creative_fatigue",
              "target_community": {"name": persona.get("name"), "one_liner": persona.get("one_liner"), "tone": persona.get("tone"),
                                   "do": persona.get("do"), "dont": persona.get("dont"), "keywords": keywords[:10]},
              "memory": [{"insight": m["insight"], "winner": m["winner"]} for m in memory]}
    if extra_note:
        inputs["note"] = extra_note

    def fallback():
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

    data, src = provider.generate("variants", _prompt("strategist", b, platform), inputs, VARIANTS_SCHEMA, Variants, 0.8, fallback)
    variants = data["variants"][:3]
    emb = get_embedder()
    orig_vec = emb.embed([creative_text(original)])[0]
    seen, ok = set(), []
    for v in variants:
        vec = emb.embed([creative_text(v)])[0]
        sim = float(vec @ orig_vec)
        if v["changed_dimension"] in seen or sim > 0.92:
            continue
        seen.add(v["changed_dimension"])
        v.update({"similarity_to_original": round(sim, 3), "emb": vec, "guard": guard.check(v, b)})
        ok.append(v)
    if len(ok) < 3 and extra_note is None and src not in ("template", "cache"):
        return generate_variants(ad, diag, persona, keywords, memory, company_cfg, platform,
                                 extra_note="Previous answer repeated a dimension or was too close to the original. Use 3 different dimensions and change them substantially.")
    if len(ok) < 2:
        for v in fallback()["variants"]:
            if v["changed_dimension"] not in seen:
                vec = emb.embed([creative_text(v)])[0]
                v.update({"similarity_to_original": round(float(vec @ orig_vec), 3), "emb": vec, "guard": guard.check(v, b)})
                ok.append(v)
                seen.add(v["changed_dimension"])
        src = src + "+template"
    return ok[:3], src


# ---------------- learning writer ----------------
def write_learning(exp_summary: dict, community_name: str, pack: str | None, day: int, company_id: str, channel_id: str, b: dict) -> tuple[dict, str]:
    def fallback():
        w = exp_summary["winner_arm"]
        base = exp_summary["arms"][0]
        if w["ad_id"] == base["ad_id"]:
            ins = f"For {community_name}, none of the tested changes beat the original {exp_summary['metric']}."
        else:
            ins = f"For {community_name}, changing the {w['changed_dimension'].replace('_', ' ')} beat the original on {exp_summary['metric']}."
        return {"insight": ins, "evidence": f"{w['ad_id']} {w['rate']:.2%} vs original {base['rate']:.2%}, P(best) {w['p_best']:.0%}",
                "community": community_name, "dimension": w.get("changed_dimension") or "none"}

    data, src = provider.generate("learning", _prompt("learning", b), exp_summary, LEARNING_SCHEMA, Learning, 0.3, fallback)
    vec = get_embedder().embed([data["insight"]])[0]
    winner_is_variant = exp_summary["winner_arm"]["ad_id"] != exp_summary["arms"][0]["ad_id"]
    mid = db.x("INSERT INTO memory(company_id,brand,insight,evidence,applies_to,winner,embedding,created_day,channel_id) VALUES (?,?,?,?,?,?,?,?,?)",
               (company_id, b["name"], data["insight"], data["evidence"], json.dumps({"pack": pack, "community": data["community"], "dimension": data["dimension"]}),
                int(winner_is_variant), db.blob(vec), day, channel_id))
    data["id"] = mid
    return data, src
