"""
utils.py — чистые функции без Streamlit-зависимостей.
Импортируются как app.py, так и тестами.
"""
import math
import pandas as pd


# ─────────────────────────────────────────────
#  MATH HELPERS
# ─────────────────────────────────────────────

def american_to_decimal(v: float) -> float:
    return round(v / 100 + 1, 4) if v >= 0 else round(100 / abs(v) + 1, 4)


def decimal_to_implied(d: float) -> float:
    return round(1 / d * 100, 2) if d > 0 else 0.0


def no_vig_prob(probs: list) -> list:
    t = sum(probs)
    return [round(p / t * 100, 2) for p in probs] if t else probs


def ev_edge(fair: float, dec: float) -> float:
    return round(fair / 100 * dec - 1, 4)


def fmt_am(v) -> str:
    try:
        f = float(v)
        return f"+{int(f)}" if f >= 0 else str(int(f))
    except Exception:
        return str(v)


# ─────────────────────────────────────────────
#  BUILD BETTING SIGNALS
# ─────────────────────────────────────────────

def build_betting_signals(df: pd.DataFrame, has_draw: bool) -> pd.DataFrame:
    """
    Для каждого матча агрегирует данные по всем букмекерам и выдаёт чёткий сигнал:
    - Лучший исход (макс EV Edge)
    - Консенсус букмекеров (доля книг с EV > 0)
    - Средняя no-vig вероятность
    - Лучший коэфф (max decimal odds)
    - Уровень уверенности сигнала (0–100)
    """
    signals = []

    if df.empty or "Матч" not in df.columns:
        return pd.DataFrame()
    for match, grp in df.groupby("Матч"):
        home = grp["Хозяева"].iloc[0]
        away = grp["Гости"].iloc[0]
        time_str = grp["Время"].iloc[0]

        outcome_data = {}

        for _, row in grp.iterrows():
            h_am = row.get("Odds Хозяева (Am)")
            a_am = row.get("Odds Гости (Am)")
            if h_am is None or a_am is None or str(h_am) == "nan" or str(a_am) == "nan":
                continue
            try:
                h_dec  = american_to_decimal(float(h_am))
                a_dec  = american_to_decimal(float(a_am))
                h_impl = decimal_to_implied(h_dec)
                a_impl = decimal_to_implied(a_dec)
                d_am   = row.get("Odds Ничья (Am)")
                if has_draw and d_am and str(d_am) != "nan":
                    d_dec  = american_to_decimal(float(d_am))
                    d_impl = decimal_to_implied(d_dec)
                    nv     = no_vig_prob([h_impl, a_impl, d_impl])
                    pairs  = [(home,    h_dec, h_impl, nv[0], fmt_am(h_am)),
                              (away,    a_dec, a_impl, nv[1], fmt_am(a_am)),
                              ("Ничья", d_dec, d_impl, nv[2], fmt_am(d_am))]
                else:
                    nv    = no_vig_prob([h_impl, a_impl])
                    pairs = [(home, h_dec, h_impl, nv[0], fmt_am(h_am)),
                             (away, a_dec, a_impl, nv[1], fmt_am(a_am))]

                for name, dec, impl, fair, am_str in pairs:
                    edge = ev_edge(fair, dec) * 100
                    if name not in outcome_data:
                        outcome_data[name] = []
                    outcome_data[name].append({
                        "dec": dec, "impl": impl, "fair": fair,
                        "edge": edge, "bm": row["Букмекер"], "am": am_str,
                    })
            except Exception:
                continue

        if not outcome_data:
            continue

        total_bm_count = len(grp["Букмекер"].unique())
        best_outcome = None
        best_edge    = -999
        outcome_stats = {}

        for name, entries in outcome_data.items():
            edges    = [e["edge"] for e in entries]
            fairs    = [e["fair"] for e in entries]
            decs     = [e["dec"]  for e in entries]
            positive = [e for e in entries if e["edge"] > 0]
            consensus_pct = round(len(positive) / total_bm_count * 100)

            avg_edge  = round(sum(edges) / len(edges), 2)
            max_edge  = round(max(edges), 2)
            avg_fair  = round(sum(fairs) / len(fairs), 1)
            best_dec  = max(decs)
            best_bm   = next(e["bm"] for e in entries if e["dec"] == best_dec)
            best_am   = next(e["am"] for e in entries if e["dec"] == best_dec)

            confidence = min(100, int(
                (max(avg_edge, 0) * 4)
                + (consensus_pct * 0.4)
                + (min(avg_fair - 33, 30))
            ))

            outcome_stats[name] = {
                "avg_edge": avg_edge, "max_edge": max_edge,
                "avg_fair": avg_fair, "best_dec": best_dec,
                "best_bm": best_bm,  "best_am": best_am,
                "consensus_pct": consensus_pct,
                "confidence": confidence,
                "books_count": len(entries),
            }
            if max_edge > best_edge:
                best_edge    = max_edge
                best_outcome = name

        if best_outcome is None:
            continue

        bs = outcome_stats[best_outcome]

        if bs["confidence"] >= 70:
            signal_emoji, signal_text = "🟢", "СИЛЬНЫЙ"
        elif bs["confidence"] >= 40:
            signal_emoji, signal_text = "🟡", "УМЕРЕННЫЙ"
        elif bs["avg_edge"] > 0:
            signal_emoji, signal_text = "🔵", "СЛАБЫЙ"
        else:
            signal_emoji, signal_text = "⚪", "НЕТ"

        other_outcomes = [
            f"{n}: EV {s['avg_edge']:+.1f}% / fair {s['avg_fair']:.0f}%"
            for n, s in outcome_stats.items() if n != best_outcome
        ]

        signals.append({
            "Матч":             match,
            "Время":            time_str,
            "Сигнал":           f"{signal_emoji} {signal_text}",
            "На кого ставить":  best_outcome,
            "Лучший букмекер":  bs["best_bm"],
            "Odds (Am)":        bs["best_am"],
            "Odds (Dec)":       bs["best_dec"],
            "EV Edge %":        f"{bs['max_edge']:+.2f}%",
            "No-Vig Fair %":    f"{bs['avg_fair']:.1f}%",
            "Консенсус книг":   f"{bs['consensus_pct']}%  ({bs['books_count']}/{total_bm_count})",
            "Уверенность":      bs["confidence"],
            "Другие исходы":    " | ".join(other_outcomes),
            "_conf":            bs["confidence"],
            "_edge":            bs["max_edge"],
        })

    if not signals:
        return pd.DataFrame()
    return pd.DataFrame(signals).sort_values(
        ["_conf", "_edge"], ascending=False
    ).reset_index(drop=True)


# ─────────────────────────────────────────────
#  COMPUTE VALUE BETS
# ─────────────────────────────────────────────

def compute_value_bets(df: pd.DataFrame, has_draw: bool, min_edge_pct: float) -> pd.DataFrame:
    rows = []
    for _, r in df.iterrows():
        h_am = r.get("Odds Хозяева (Am)")
        a_am = r.get("Odds Гости (Am)")
        if h_am is None or a_am is None or str(h_am) == "nan" or str(a_am) == "nan":
            continue
        try:
            h_dec  = american_to_decimal(float(h_am))
            a_dec  = american_to_decimal(float(a_am))
            h_impl = decimal_to_implied(h_dec)
            a_impl = decimal_to_implied(a_dec)
            d_am   = r.get("Odds Ничья (Am)")
            if has_draw and d_am and str(d_am) != "nan":
                d_dec  = american_to_decimal(float(d_am))
                d_impl = decimal_to_implied(d_dec)
                nv     = no_vig_prob([h_impl, a_impl, d_impl])
                candidates = [(r["Хозяева"], h_dec, h_impl, nv[0], fmt_am(h_am)),
                              (r["Гости"],   a_dec, a_impl, nv[1], fmt_am(a_am)),
                              ("Ничья",      d_dec, d_impl, nv[2], fmt_am(d_am))]
            else:
                nv = no_vig_prob([h_impl, a_impl])
                candidates = [(r["Хозяева"], h_dec, h_impl, nv[0], fmt_am(h_am)),
                              (r["Гости"],   a_dec, a_impl, nv[1], fmt_am(a_am))]
            for name, dec, impl, fair, am_str in candidates:
                edge = ev_edge(fair, dec) * 100
                if edge >= min_edge_pct:
                    rows.append({
                        "Матч":         r["Матч"],
                        "Время":        r["Время"],
                        "Букмекер":     r["Букмекер"],
                        "Исход":        f"✅ {name}",
                        "Odds (Am)":    am_str,
                        "Odds (Dec)":   dec,
                        "Implied %":    f"{impl}%",
                        "No-Vig Fair %": f"{fair}%",
                        "EV Edge %":    f"+{edge:.2f}%",
                        "_edge":        edge,
                    })
        except Exception:
            continue

    if rows:
        vdf = pd.DataFrame(rows).sort_values("_edge", ascending=False).reset_index(drop=True)
        vdf.index += 1
        return vdf.drop(columns=["_edge"])
    return pd.DataFrame()


# ─────────────────────────────────────────────
#  TEST HELPERS (also used in tests)
# ─────────────────────────────────────────────

def make_h2h_row(match, home, away, bm, h_am, a_am,
                 d_am=None, time="15.04 12:00 МСК"):
    """Creates one DataFrame row in parse_to_df format (h2h market)."""
    return {
        "Матч":               match,
        "Хозяева":            home,
        "Гости":              away,
        "Букмекер":           bm,
        "Время":              time,
        "Odds Хозяева (Am)":  h_am,
        "Odds Гости (Am)":    a_am,
        "Odds Ничья (Am)":    d_am,
    }
