"""
InsightAgent 
"""

from __future__ import annotations
import asyncio, math, time
from typing import Any
from collections import Counter

from mivais.base_agent import BaseAgent
from spec_utils import choose_mark, enumerate_specs, score_effectiveness, view_to_spec


class InsightAgent(BaseAgent):
    """Proactive insight generation — the system's voice."""

    _COOLDOWN = 8.0

    async def run(self) -> None:
        self._last_sent: dict[str, float] = {}  # insight_key -> timestamp
        self._subscribe("chat.message")
        self._subscribe("insight.action_selected")
        self._ws.watch("focus_view", self._on_focus_changed)
        self._ws.watch("current_spec", self._on_spec_changed)
        await asyncio.Event().wait()

    async def on_message(self, message: dict) -> None:
        if message.get("topic") == "insight.action_selected":
            await self._apply_action((message.get("payload") or {}).get("suggestion") or {})

    async def _apply_action(self, suggestion: dict) -> None:
        if suggestion.get("spec"):
            self._write("current_spec", view_to_spec(suggestion["spec"]))
        elif suggestion.get("filter_nulls"):
            field = suggestion["filter_nulls"].get("field")
            if field:
                data_fields = self._read("data_fields") or []
                ftype = next((f["type"] for f in data_fields if f["field"] == field), "nominal")
                filters = [
                    f for f in (self._read("filters") or [])
                    if not (f.get("field") == field and f.get("valid"))
                ]
                filters.append({"field": field, "type": "nominal" if ftype == "nominal" else "quantitative", "valid": True})
                self._write("filters", filters)
        await self._publish("recommendation.instruction", {"suggestion": suggestion})

    async def _on_spec_changed(self, key: str, value: Any) -> None:
        spec = value
        if not spec:
            return

        data_fields = self._read("data_fields") or []
        if not data_fields:
            return

        try:
            has_wildcards = self._has_wildcards(spec)

            if has_wildcards:
                results = enumerate_specs(spec, data_fields, max_results=30)
                self._write("wildcard_results", results)
                self._write("focus_view", results[0] if results else None)
            else:
                self._write("wildcard_results", [])
                focus = self._build_concrete(spec)
                if focus:
                    self._write("focus_view", focus)
        except Exception as exc:
            print(f"[{self.agent_id}] error: {exc}")

    def _has_wildcards(self, spec: dict) -> bool:
        if spec.get("mark") == "?":
            return True
        for enc in spec.get("encodings", []):
            for key in ["channel", "field", "type"]:
                val = str(enc.get(key, ""))
                if val == "?" or val.startswith("?"):
                    return True
        return False

    def _build_concrete(self, spec: dict) -> dict | None:
        encodings_list = spec.get("encodings", [])
        if not encodings_list:
            return None

        encoding = {}
        for enc in encodings_list:
            ch = enc.get("channel")
            if not ch or ch == "?":
                continue
            enc_dict = {"field": enc["field"], "type": enc.get("type", "nominal")}
            if enc.get("aggregate"):
                enc_dict["aggregate"] = enc["aggregate"]
            if enc.get("bin"):
                enc_dict["bin"] = True
            if enc.get("timeUnit"):
                enc_dict["timeUnit"] = enc["timeUnit"]
            encoding[ch] = enc_dict

        if not encoding:
            return None

        mark = spec.get("mark", "?")
        if mark == "?":
            mark = choose_mark(encoding)

        result = {"mark": mark, "encoding": encoding}
        result["_score"] = score_effectiveness(result)
        return result

    async def _on_focus_changed(self, key: str, value: Any) -> None:
        focus = value
        if not focus or not focus.get("encoding"):
           
            await self._analyse_overview()
            return

        dataset = self._read("dataset")
        data_fields = self._read("data_fields")
        if not dataset or not data_fields:
            return

        encoding = focus.get("encoding", {})
        insights = []

        # Collect all analyses
        insights.extend(self._check_correlations(encoding, dataset, data_fields))
        insights.extend(self._check_missing_values(encoding, dataset))
        insights.extend(self._check_outliers(encoding, dataset))
        insights.extend(self._check_skew(encoding, dataset))
        insights.extend(self._check_cardinality(encoding, dataset))
        insights.extend(self._check_dominant_category(encoding, dataset))

        # Generate actionable suggestions for each insight
        self._add_suggestions(insights, encoding, data_fields)

        # Publish top insights (max 2 per focus change to avoid flooding)
        sent = 0
        for insight in insights:
            if sent >= 2:
                break
            ikey = insight.get("_key", "")
            now = time.time()
            if ikey and now - self._last_sent.get(ikey, 0) < self._COOLDOWN:
                continue
            self._last_sent[ikey] = now
            await self._publish("chat.message", self._to_chat(insight))
            sent += 1

    async def _analyse_overview(self) -> None:
        """Send a welcome insight when no focus view is set."""
        ikey = "overview"
        now = time.time()
        if now - self._last_sent.get(ikey, 0) < 30:
            return
        self._last_sent[ikey] = now

        dataset = self._read("dataset")
        data_fields = self._read("data_fields")
        if not dataset or not data_fields:
            return

        real_fields = [f for f in data_fields if not f.get("is_count")]
        q_fields = [f for f in real_fields if f["type"] == "quantitative"]
        n_fields = [f for f in real_fields if f["type"] == "nominal"]
        t_fields = [f for f in real_fields if f["type"] == "temporal"]

        # Count missing values across all fields
        total_missing = 0
        for f in real_fields:
            total_missing += sum(1 for row in dataset if row.get(f["field"]) is None)

        text = (
            f"[i] Dataset loaded: {len(dataset)} rows, "
            f"{len(q_fields)} quantitative, {len(n_fields)} nominal, "
            f"{len(t_fields)} temporal fields."
        )
        if total_missing > 0:
            text += f" {total_missing} missing values detected across all fields."
        text += " Drag a field to a shelf to start exploring."

        await self._publish("chat.message", {
            "from": self.agent_id,
            "from_display": "Insight Agent",
            "to": "broadcast",
            "text": text,
            "timestamp": time.time(),
        })

    # ── Analysis methods ──────────────────────────────────────────────────────

    def _check_correlations(self, encoding: dict, dataset: list, data_fields: list) -> list:
        """Check pairwise correlations between quantitative fields in the view."""
        q_fields = []
        for ch, enc in encoding.items():
            if enc.get("type") == "quantitative" and enc.get("field") != "*":
                q_fields.append(enc["field"])

        if len(q_fields) < 2:
            return []

        insights = []
        for i in range(len(q_fields)):
            for j in range(i + 1, len(q_fields)):
                f1, f2 = q_fields[i], q_fields[j]
                r = self._pearson(dataset, f1, f2)
                if r is None:
                    continue
                abs_r = abs(r)
                if abs_r >= 0.8:
                    direction = "positive" if r > 0 else "negative"
                    insights.append({
                        "level": "info",
                        "title": "Strong correlation",
                        "text": f"[mark:{f1}] and [mark:{f2}] show a strong {direction} correlation (r={r:.2f}). "
                                f"Changes in one tend to {'increase' if r > 0 else 'decrease'} with the other.",
                        "_key": f"corr:{f1}:{f2}",
                        "_priority": abs_r,
                    })
                elif abs_r >= 0.5:
                    direction = "positive" if r > 0 else "negative"
                    insights.append({
                        "level": "info",
                        "title": "Moderate correlation",
                        "text": f"[mark:{f1}] and [mark:{f2}] have a moderate {direction} correlation (r={r:.2f}).",
                        "_key": f"corr:{f1}:{f2}",
                        "_priority": abs_r,
                    })
        insights.sort(key=lambda x: x.get("_priority", 0), reverse=True)
        return insights

    def _check_missing_values(self, encoding: dict, dataset: list) -> list:
        """Flag fields with missing values."""
        insights = []
        for ch, enc in encoding.items():
            fname = enc.get("field")
            if not fname or fname == "*":
                continue
            missing = sum(1 for row in dataset if row.get(fname) is None)
            if missing > 0:
                pct = missing / len(dataset) * 100
                level = "warning" if pct > 10 else "info"
                insights.append({
                    "level": level,
                    "title": "Missing values",
                    "text": f"[mark:{fname}] has {missing} missing values ({pct:.0f}% of rows). "
                            f"{'Consider filtering these out.' if pct > 10 else 'This may affect aggregations.'}",
                    "_key": f"missing:{fname}",
                    "_priority": pct,
                })
        insights.sort(key=lambda x: x.get("_priority", 0), reverse=True)
        return insights

    def _check_outliers(self, encoding: dict, dataset: list) -> list:
        """Detect outliers using IQR method."""
        insights = []
        for ch, enc in encoding.items():
            if enc.get("type") != "quantitative" or enc.get("field") == "*":
                continue
            fname = enc["field"]
            vals = sorted(v for row in dataset if (v := row.get(fname)) is not None and isinstance(v, (int, float)))
            if len(vals) < 10:
                continue

            q1 = vals[len(vals) // 4]
            q3 = vals[3 * len(vals) // 4]
            iqr = q3 - q1
            if iqr == 0:
                continue

            lower = q1 - 1.5 * iqr
            upper = q3 + 1.5 * iqr
            outliers = [v for v in vals if v < lower or v > upper]

            if len(outliers) >= 3:
                insights.append({
                    "level": "info",
                    "title": "Outliers detected",
                    "text": f"[mark:{fname}] has {len(outliers)} outliers outside the IQR range "
                            f"[{lower:.1f}, {upper:.1f}]. The most extreme value is {max(abs(min(outliers)), abs(max(outliers))):.1f}.",
                    "_key": f"outlier:{fname}",
                    "_priority": len(outliers) / len(vals),
                })
        return insights

    def _check_skew(self, encoding: dict, dataset: list) -> list:
        """Check for heavily skewed distributions."""
        insights = []
        for ch, enc in encoding.items():
            if enc.get("type") != "quantitative" or enc.get("field") == "*":
                continue
            fname = enc["field"]
            vals = [v for row in dataset if (v := row.get(fname)) is not None and isinstance(v, (int, float))]
            if len(vals) < 20:
                continue

            mean = sum(vals) / len(vals)
            median = sorted(vals)[len(vals) // 2]
            std = math.sqrt(sum((v - mean) ** 2 for v in vals) / len(vals))
            if std == 0:
                continue

            skewness = sum((v - mean) ** 3 for v in vals) / (len(vals) * std ** 3)

            if abs(skewness) > 1.5:
                direction = "right (positive)" if skewness > 0 else "left (negative)"
                insights.append({
                    "level": "info",
                    "title": "Skewed distribution",
                    "text": f"[mark:{fname}] is heavily skewed {direction} (skewness={skewness:.2f}). "
                            f"Consider using a log scale or binning for clearer visualization.",
                    "_key": f"skew:{fname}",
                    "_priority": abs(skewness),
                })
        return insights

    def _check_cardinality(self, encoding: dict, dataset: list) -> list:
        """Warn about high-cardinality nominal fields."""
        insights = []
        for ch, enc in encoding.items():
            if enc.get("type") != "nominal" or enc.get("field") == "*":
                continue
            fname = enc["field"]
            vals = [row.get(fname) for row in dataset if row.get(fname) is not None]
            unique = len(set(vals))

            if unique > 20 and ch in ("color", "shape"):
                insights.append({
                    "level": "warning",
                    "title": "High cardinality",
                    "text": f"[mark:{fname}] has {unique} unique values on the {ch} channel. "
                            f"This may produce an unreadable chart. Consider filtering or using row/column faceting instead.",
                    "_key": f"cardinality:{fname}:{ch}",
                    "_priority": unique,
                })
            elif unique <= 3 and ch in ("x", "y"):
                insights.append({
                    "level": "info",
                    "title": "Low cardinality",
                    "text": f"[mark:{fname}] has only {unique} unique values. "
                            f"Consider using it as color or shape instead of a positional axis.",
                    "_key": f"lowcard:{fname}",
                    "_priority": 1,
                })
        return insights

    def _check_dominant_category(self, encoding: dict, dataset: list) -> list:
        """Detect if one category dominates a nominal field."""
        insights = []
        for ch, enc in encoding.items():
            if enc.get("type") != "nominal" or enc.get("field") == "*":
                continue
            fname = enc["field"]
            vals = [row.get(fname) for row in dataset if row.get(fname) is not None]
            if not vals:
                continue
            counts = Counter(vals)
            total = len(vals)
            most_common_val, most_common_count = counts.most_common(1)[0]
            pct = most_common_count / total * 100

            if pct > 60 and len(counts) > 1:
                insights.append({
                    "level": "info",
                    "title": "Dominant category",
                    "text": f"[mark:{fname}]: '{most_common_val}' accounts for {pct:.0f}% of all values. "
                            f"The distribution is heavily imbalanced.",
                    "_key": f"dominant:{fname}",
                    "_priority": pct,
                })
        return insights

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _pearson(self, dataset: list, f1: str, f2: str) -> float | None:
        """Compute Pearson correlation between two fields."""
        pairs = []
        for row in dataset:
            v1, v2 = row.get(f1), row.get(f2)
            if v1 is not None and v2 is not None and isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
                pairs.append((float(v1), float(v2)))
        if len(pairs) < 5:
            return None

        n = len(pairs)
        sx = sum(a for a, b in pairs)
        sy = sum(b for a, b in pairs)
        sxy = sum(a * b for a, b in pairs)
        sx2 = sum(a * a for a, b in pairs)
        sy2 = sum(b * b for a, b in pairs)

        denom = math.sqrt((n * sx2 - sx ** 2) * (n * sy2 - sy ** 2))
        if denom == 0:
            return None
        return (n * sxy - sx * sy) / denom

    def _add_suggestions(self, insights: list, encoding: dict, data_fields: list) -> None:
        """Add actionable next-step suggestions to insights."""
        used_fields = {e.get("field") for e in encoding.values() if e.get("field")}
        used_channels = set(encoding.keys())

        for insight in insights:
            ikey = insight.get("_key", "")

            if ikey.startswith("corr:"):
                
                for f in data_fields:
                    if f["type"] == "nominal" and f["field"] not in used_fields and not f.get("is_count"):
                        new_enc = {c: dict(e) for c, e in encoding.items()}
                        if "color" not in used_channels:
                            new_enc["color"] = {"field": f["field"], "type": "nominal"}
                            insight["suggestion"] = {
                                "label": f"Color by {f['field']} to reveal subgroups",
                                "spec": {"mark": "point", "encoding": new_enc},
                            }
                        break

            elif ikey.startswith("missing:"):
                fname = ikey.split(":", 1)[1]
                insight["suggestion"] = {
                    "label": f"Filter out rows where {fname} is null",
                    
                    "filter_nulls": {"field": fname},
                }

            elif ikey.startswith("skew:"):
                fname = ikey.split(":", 1)[1]
                # Suggest binning the field
                new_enc = {c: dict(e) for c, e in encoding.items()}
                for ch, e in new_enc.items():
                    if e.get("field") == fname:
                        e["bin"] = True
                        break
                insight["suggestion"] = {
                    "label": f"Bin {fname} for a clearer histogram view",
                    "spec": {"mark": "bar", "encoding": new_enc},
                }

            elif ikey.startswith("outlier:"):
                fname = ikey.split(":", 1)[1]
                # Suggest switching to a boxplot-like view (tick + color)
                for f in data_fields:
                    if f["type"] == "nominal" and f["field"] not in used_fields and not f.get("is_count"):
                        new_enc = {}
                        new_enc["x"] = {"field": f["field"], "type": "nominal"}
                        new_enc["y"] = {"field": fname, "type": "quantitative"}
                        insight["suggestion"] = {
                            "label": f"Compare {fname} across {f['field']} groups",
                            "spec": {"mark": "tick", "encoding": new_enc},
                        }
                        break

            elif ikey.startswith("lowcard:"):
                fname = ikey.split(":", 1)[1]
                ftype = next((f["type"] for f in data_fields if f["field"] == fname), "nominal")
                insight["suggestion"] = {
                    "label": f"Move {fname} to color encoding",
                    "add_field": {"field": fname, "type": ftype},
                }

            elif ikey.startswith("dominant:"):
                fname = ikey.split(":", 1)[1]
                # Suggest a histogram of the field
                insight["suggestion"] = {
                    "label": f"View full distribution of {fname}",
                    "spec": {
                        "mark": "bar",
                        "encoding": {
                            "y": {"field": fname, "type": "nominal"},
                            "x": {"field": "*", "type": "quantitative", "aggregate": "count"},
                        },
                    },
                }

    def _to_chat(self, insight: dict) -> dict:
        """Convert an insight dict to a chat message payload."""
        level = insight.get("level", "info")
        prefix = {"warning": "[!]", "ok": "[ok]", "info": "[i]"}.get(level, "[i]")
        text = f"{prefix} **{insight['title']}** — {insight.get('text', '')}"

        # Append suggestion text
        suggestion = insight.get("suggestion")
        if suggestion and suggestion.get("label"):
            text += f"\n> Next step: {suggestion['label']}"

        payload = {
            "from": self.agent_id,
            "from_display": "Insight Agent",
            "to": "broadcast",
            "text": text,
            "timestamp": time.time(),
        }

        
        if suggestion or insight.get("title"):
            payload["_popover"] = {
                "level": level,
                "title": insight.get("title", ""),
                "text": insight.get("text", ""),
                "suggestion": suggestion,
            }

        return payload
