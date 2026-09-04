"""
CompassQL-like specification engine for Voyager 2.

Handles partial specifications with wildcards, enumerates valid completions,
ranks by perceptual effectiveness, and groups results.

Based on: Wongsuphasawat et al., "Voyager 2: Augmenting Visual Analysis
with Partial View Specifications", CHI 2017.
"""

from __future__ import annotations
import itertools, math, hashlib, json
from typing import Any

# ── Field types ────────────────────────────────────────────────────────────────
Q = "quantitative"
N = "nominal"
T = "temporal"
O = "ordinal"
FIELD_TYPES = {Q, N, T, O}

# ── Channels ───────────────────────────────────────────────────────────────────
POSITION_CHANNELS = ["x", "y"]
NON_POSITION_CHANNELS = ["color", "size", "shape", "row", "column"]
ALL_CHANNELS = POSITION_CHANNELS + NON_POSITION_CHANNELS

# ── Mark types ─────────────────────────────────────────────────────────────────
MARK_TYPES = ["point", "bar", "line", "area", "tick", "rect"]

# ── Aggregation functions ──────────────────────────────────────────────────────
AGG_FUNCTIONS = [None, "mean", "median", "min", "max", "sum", "count"]
BIN_OPTIONS = [False, True]
TIME_UNITS = [None, "year", "month", "day", "hours"]

# ── Effectiveness scores (higher = better) ─────────────────────────────────────
# Based on Bertin, Cleveland, Mackinlay — position > length/size > color > shape
CHANNEL_EFFECTIVENESS = {
    Q: {"x": 10, "y": 9, "size": 6, "color": 5, "row": 4, "column": 4, "shape": 0},
    N: {"x": 8, "y": 7, "color": 6, "shape": 5, "row": 7, "column": 7, "size": 0},
    T: {"x": 10, "y": 9, "color": 4, "size": 3, "row": 3, "column": 3, "shape": 0},
    O: {"x": 9, "y": 8, "color": 5, "size": 4, "row": 5, "column": 5, "shape": 3},
}

# ── Expressiveness constraints ─────────────────────────────────────────────────
# Which channels can express which field types
EXPRESSIVE_CHANNELS = {
    Q: {"x", "y", "size", "color", "row", "column"},
    N: {"x", "y", "color", "shape", "row", "column"},
    T: {"x", "y", "color", "row", "column"},
    O: {"x", "y", "color", "size", "shape", "row", "column"},
}


def infer_field_types(dataset: list[dict]) -> list[dict]:
    """Infer field metadata (name + type) from a tabular dataset."""
    if not dataset:
        return []
    fields = []
    sample_size = min(200, len(dataset))
    
    cardinality = {
        col: len({str(row.get(col)) for row in dataset if row.get(col) is not None})
        for col in dataset[0].keys()
    }
    for col in dataset[0].keys():
        
        values = [row.get(col) for row in dataset if row.get(col) is not None][:sample_size]
        if not values:
            fields.append({"field": col, "type": N})
            continue
        
        numeric_count = sum(1 for v in values if isinstance(v, (int, float)))
        if numeric_count / len(values) > 0.8:
            fields.append({"field": col, "type": Q})
            continue
        
        str_vals = [str(v) for v in values]
        if any(kw in col.lower() for kw in ["date", "time", "year", "month", "day"]):
            fields.append({"field": col, "type": T})
            continue
        
        unique = len(set(str(v) for v in values))
        if unique <= 10 and all(isinstance(v, (int, float)) for v in values):
            fields.append({"field": col, "type": O})
        else:
            fields.append({"field": col, "type": N})
    
    fields.append({"field": "*", "type": Q, "is_count": True})
    for f in fields:
        f["cardinality"] = cardinality.get(f["field"], 0)
    return fields


def _spec_hash(spec: dict) -> str:
    """Deterministic hash for deduplication."""
    canonical = json.dumps(spec, sort_keys=True, default=str)
    return hashlib.md5(canonical.encode()).hexdigest()[:12]


def score_effectiveness(spec: dict) -> float:
    """Score a complete Vega-Lite-like spec by perceptual effectiveness."""
    score = 0.0
    encodings = spec.get("encoding", {})
    for channel, enc in encodings.items():
        ftype = enc.get("type", N)
        ch_scores = CHANNEL_EFFECTIVENESS.get(ftype, {})
        score += ch_scores.get(channel, 0)
    
    for enc in encodings.values():
        if enc.get("aggregate"):
            score -= 0.5
        if enc.get("bin"):
            score -= 0.3
    
    mark = spec.get("mark", "point")
    enc_types = set(e.get("type") for e in encodings.values())
    if mark == "point" and Q in enc_types:
        score += 1
    if mark == "bar" and N in enc_types and Q in enc_types:
        score += 1
    if mark == "line" and T in enc_types:
        score += 1.5
    return score


def choose_mark(encodings: dict) -> str:
    """Choose the best mark type given the encodings."""
    types = set()
    for enc in encodings.values():
        types.add(enc.get("type", N))
    has_q = Q in types
    has_n = N in types
    has_t = T in types
    channels = set(encodings.keys())
    
    pos_types = [encodings[c].get("type") for c in ["x", "y"] if c in encodings]
    if pos_types.count(Q) == 2:
        return "point"
    if has_t and has_q:
        return "line"
    if has_n and has_q:
        return "bar"
    if len(encodings) == 1:
        enc = list(encodings.values())[0]
        if enc.get("type") == Q:
            return "bar" if enc.get("bin") or enc.get("aggregate") == "count" else "tick"
        return "bar"
    if has_q:
        return "bar"
    return "bar"


def is_expressive(channel: str, field_type: str) -> bool:
    """Check if a channel can expressively encode a given field type."""
    return channel in EXPRESSIVE_CHANNELS.get(field_type, set())


def enumerate_specs(
    partial_spec: dict,
    data_fields: list[dict],
    max_results: int = 30,
) -> list[dict]:
    """
    Enumerate valid complete specs from a partial specification with wildcards.

    Returns a list of complete Vega-Lite-like specs, ranked by effectiveness.
    """
    enc_list = partial_spec.get("encodings", [])
    mark = partial_spec.get("mark", "?")

    
    resolved_encs_options = []  
    for enc in enc_list:
        options = _resolve_encoding(enc, data_fields)
        if options:
            resolved_encs_options.append(options)

    if not resolved_encs_options:
        return []

    
    results = []
    seen = set()
    for combo in itertools.product(*resolved_encs_options):
        
        channels_used = [c for c, _ in combo]
        if len(channels_used) != len(set(channels_used)):
            continue
        
        fields_used = [e.get("field") for _, e in combo if e.get("field") != "*"]
        if len(fields_used) != len(set(fields_used)):
            continue

        encoding = {}
        for ch, enc_dict in combo:
            encoding[ch] = enc_dict

        
        m = mark if mark != "?" else choose_mark(encoding)

        spec = {"mark": m, "encoding": encoding}
        h = _spec_hash(spec)
        if h not in seen:
            seen.add(h)
            spec["_score"] = score_effectiveness(spec)
            results.append(spec)

    
    results.sort(key=lambda s: s["_score"], reverse=True)
    return results[:max_results]


def _resolve_encoding(enc: dict, data_fields: list[dict]) -> list[tuple[str, dict]]:
    """Resolve wildcards in a single encoding, returning list of (channel, enc_dict)."""
    channel = enc.get("channel", "?")
    field = enc.get("field", "?")
    ftype = enc.get("type", "?")
    aggregate = enc.get("aggregate", None)
    bin_val = enc.get("bin", False)
    time_unit = enc.get("timeUnit", None)

    
    if field == "?":
        field_options = data_fields
    elif field == "?Q":
        field_options = [f for f in data_fields if f["type"] == Q and not f.get("is_count")]
    elif field == "?N":
        field_options = [f for f in data_fields if f["type"] == N]
    elif field == "?T":
        field_options = [f for f in data_fields if f["type"] == T]
    elif field == "?O":
        field_options = [f for f in data_fields if f["type"] == O]
    else:
        
        match = [f for f in data_fields if f["field"] == field]
        if not match:
            return []
        field_options = match

    
    if channel == "?":
        channel_options = ALL_CHANNELS
    elif channel == "?position":
        channel_options = POSITION_CHANNELS
    else:
        channel_options = [channel]

    
    results = []
    for f in field_options:
        fname = f["field"]
        ft = f["type"] if ftype == "?" else ftype

        
        agg = aggregate
        b = bin_val
        tu = time_unit

        
        if f.get("is_count"):
            agg = "count"
            fname = "*"
            ft = Q

        for ch in channel_options:
            if not is_expressive(ch, ft):
                continue
            enc_dict = {"field": fname, "type": ft}
            if agg:
                enc_dict["aggregate"] = agg
            if b:
                enc_dict["bin"] = True
            if tu:
                enc_dict["timeUnit"] = tu
            results.append((ch, enc_dict))

    return results


# ── Recommendation generators ─────────────────────────────────────────────────

def generate_univariate_summaries(data_fields: list[dict]) -> list[dict]:
    """Generate univariate summary views for all fields (histograms, bar charts)."""
    specs = []
    for f in data_fields:
        if f.get("is_count"):
            continue
        fname = f["field"]
        ft = f["type"]
        if ft == Q:
            
            spec = {
                "mark": "bar",
                "encoding": {
                    "x": {"field": fname, "type": Q, "bin": True},
                    "y": {"field": "*", "type": Q, "aggregate": "count"},
                },
            }
        elif ft == T:
           
            spec = {
                "mark": "line",
                "encoding": {
                    "x": {"field": fname, "type": T, "timeUnit": "year"},
                    "y": {"field": "*", "type": Q, "aggregate": "count"},
                },
            }
        elif f.get("cardinality", 0) > 25:
            
            continue
        else:
            spec = {
                "mark": "bar",
                "encoding": {
                    "y": {"field": fname, "type": N},
                    "x": {"field": "*", "type": Q, "aggregate": "count"},
                },
            }
        spec["_title"] = f"Distribution of {fname}"
        spec["_score"] = score_effectiveness(spec)
        specs.append(spec)
    return specs


def generate_summaries(focus_spec: dict, data_fields: list[dict]) -> list[dict]:
    """Generate aggregate summaries of the focus view."""
    specs = []
    focus_enc = focus_spec.get("encoding", {})
    focus_fields = {e.get("field") for e in focus_enc.values()}

    for ch, enc in focus_enc.items():
        if enc.get("type") != Q or enc.get("field") == "*":
            continue
        fname = enc["field"]
        
        for agg in ["mean", "median"]:
            new_enc = {}
            for c2, e2 in focus_enc.items():
                new_e = dict(e2)
                if c2 == ch:
                    new_e["aggregate"] = agg
                    if "bin" in new_e:
                        del new_e["bin"]
                new_enc[c2] = new_e
            spec = {"mark": "bar", "encoding": new_enc}
            spec["_title"] = f"{agg.capitalize()} of {fname}"
            spec["_score"] = score_effectiveness(spec)
            specs.append(spec)

        
        new_enc = {}
        for c2, e2 in focus_enc.items():
            new_e = dict(e2)
            if c2 == ch:
                new_e["bin"] = True
                new_e.pop("aggregate", None)
            new_enc[c2] = new_e
        
        free_ch = "y" if ch == "x" else "x"
        if free_ch not in new_enc:
            new_enc[free_ch] = {"field": "*", "type": Q, "aggregate": "count"}
            spec = {"mark": "bar", "encoding": new_enc}
            spec["_title"] = f"Histogram of {fname}"
            spec["_score"] = score_effectiveness(spec)
            specs.append(spec)

    return specs[:8]


def generate_field_suggestions(
    focus_spec: dict, data_fields: list[dict]
) -> list[dict]:
    """Suggest views with one additional field beyond the focus view."""
    specs = []
    focus_enc = focus_spec.get("encoding", {})
    focus_fields = {e.get("field") for e in focus_enc.values() if e.get("field")}
    used_channels = set(focus_enc.keys())

    
    available = [ch for ch in ALL_CHANNELS if ch not in used_channels]
    if not available:
        return []

    for f in data_fields:
        if f.get("is_count") or f["field"] in focus_fields:
            continue
        if f["type"] == N and f.get("cardinality", 0) > 25:
            
            continue
        fname = f["field"]
        ft = f["type"]
        
        best_ch = None
        best_score = -1
        for ch in available:
            if is_expressive(ch, ft):
                s = CHANNEL_EFFECTIVENESS.get(ft, {}).get(ch, 0)
                if s > best_score:
                    best_score = s
                    best_ch = ch
        if best_ch is None:
            continue

        new_enc = {c: dict(e) for c, e in focus_enc.items()}
        new_enc[best_ch] = {"field": fname, "type": ft}
        mark = focus_spec.get("mark", choose_mark(new_enc))
        spec = {"mark": mark, "encoding": new_enc}
        spec["_title"] = f"+ {fname}"
        spec["_score"] = score_effectiveness(spec)
        specs.append(spec)

    specs.sort(key=lambda s: s["_score"], reverse=True)
    return specs[:10]


def generate_alt_encodings(focus_spec: dict) -> list[dict]:
    """Generate alternative encodings for the same data (same fields, different channels)."""
    focus_enc = focus_spec.get("encoding", {})
    if len(focus_enc) < 2:
        return []

    specs = []
    items = list(focus_enc.items())

    
    if "x" in focus_enc and "y" in focus_enc:
        new_enc = dict(focus_enc)
        new_enc["x"], new_enc["y"] = dict(focus_enc["y"]), dict(focus_enc["x"])
        mark = choose_mark(new_enc)
        spec = {"mark": mark, "encoding": new_enc}
        spec["_title"] = "Transposed axes"
        spec["_score"] = score_effectiveness(spec)
        specs.append(spec)

    
    for ch in ["row", "column", "size"]:
        if ch in focus_enc and "color" not in focus_enc:
            new_enc = {c: dict(e) for c, e in focus_enc.items()}
            new_enc["color"] = new_enc.pop(ch)
            mark = choose_mark(new_enc)
            spec = {"mark": mark, "encoding": new_enc}
            spec["_title"] = f"Color instead of {ch}"
            spec["_score"] = score_effectiveness(spec)
            specs.append(spec)

    
    if "color" in focus_enc and "row" not in focus_enc:
        enc_info = focus_enc["color"]
        if enc_info.get("type") in (N, O):
            new_enc = {c: dict(e) for c, e in focus_enc.items()}
            new_enc["row"] = new_enc.pop("color")
            mark = choose_mark(new_enc)
            spec = {"mark": mark, "encoding": new_enc}
            spec["_title"] = "Trellis (row) instead of color"
            spec["_score"] = score_effectiveness(spec)
            specs.append(spec)

    
    for alt_mark in MARK_TYPES:
        if alt_mark != focus_spec.get("mark"):
            spec = {"mark": alt_mark, "encoding": {c: dict(e) for c, e in focus_enc.items()}}
            spec["_title"] = f"Mark: {alt_mark}"
            spec["_score"] = score_effectiveness(spec)
            specs.append(spec)

    specs.sort(key=lambda s: s["_score"], reverse=True)
    return specs[:6]


def view_to_spec(view: dict) -> dict:
    encoding = view.get("encoding", {})
    encodings = []
    for channel, enc in encoding.items():
        e = {
            "channel": channel,
            "field": enc.get("field", ""),
            "type": enc.get("type", "nominal"),
        }
        if enc.get("aggregate"):
            e["aggregate"] = enc["aggregate"]
        if enc.get("bin"):
            e["bin"] = True
        if enc.get("timeUnit"):
            e["timeUnit"] = enc["timeUnit"]
        encodings.append(e)
    return {
        "mark": view.get("mark", "?"),
        "encodings": encodings,
    }
