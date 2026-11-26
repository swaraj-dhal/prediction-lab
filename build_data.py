#!/usr/bin/env python3
"""Builds data.json for the Prediction Lab. Each source runs in its own try/except,
so if one fails the others still load. Check data.json -> "sources" for status."""
import os, re, io, json, math, datetime as dt, statistics as st
import pandas as pd, requests

TODAY = dt.date.fromisoformat(os.environ["ASOF"]) if os.environ.get("ASOF") else dt.date.today()
OUT = os.environ.get("OUT", "data.json")
ODDS_KEY = os.environ.get("ODDS_API_KEY", "")
sources, rows = {}, []

def norm(n):
    n = re.sub(r"[^a-z ]", "", str(n).lower())
    return " ".join(re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", n).split())

def half(x): return math.floor(x) + 0.5
def get(url, **kw):
    r = requests.get(url, timeout=60, headers={"User-Agent": "prop-lab/1.0"}, **kw); r.raise_for_status(); return r

def allowed_ratio(df, opp, game, cols):
    """How many of each stat a defense allows per game vs league average (capped +-10%)."""
    t = df.groupby([opp, game])[cols].sum().reset_index().groupby(opp)[cols].mean()
    lg = t.mean()
    return {c: {k: max(-10, min(10, (v / lg[c] - 1) * 50)) for k, v in t[c].items()} for c in cols}

def injuries(league):
    """ESPN public injury feed -> {normalized name: status}. Best effort."""
    out = {}
    try:
        j = get(f"https://site.api.espn.com/apis/site/v2/sports/{league}/injuries").json()
        for team in j.get("injuries", []):
            for i in team.get("injuries", []):
                out[norm(i["athlete"]["displayName"])] = i.get("status", "")
        sources[f"injuries_{league}"] = f"ok ({len(out)} listed)"
    except Exception as e:
        sources[f"injuries_{league}"] = f"failed: {e}"
    return out

def boost(team_players, stat, out_names):
    """Teammate injury boost: share of a team's volume sitting out, half redistributed."""
    avgs = {p["name"]: st.mean(p["stats"][stat][-8:]) for p in team_players if stat in p["stats"]}
    tot = sum(avgs.values()) or 1
    o = sum(v for n, v in avgs.items() if norm(n) in out_names) / tot
    return min(25, 50 * o / max(1 - o, .3))

def finish(league, players, inj, mu_fn, lines):
    for p in players:
        for stat, log in p["stats"].items():
            if len(log) < 5: continue
            status = inj.get(norm(p["name"]), "")
            if status.lower() in ("out", "doubtful", "injured reserve", "suspension"): continue
            key = (norm(p["name"]), stat)
            line = lines.get(key)
            rows.append(dict(
                lg=league, name=p["name"], team=p["team"], opp=p["opp"], home=p["home"], g=p["gid"],
                when=p.get("when", ""), stat=stat, log=[round(x, 1) for x in log[-20:]],
                line=line if line is not None else half(st.median(log[-8:])),
                lineSource="book" if line is not None else "median",
                role=0, inj=round(boost(p["_team"], stat, {norm(n) for n, s in inj.items() if s.lower() in ("out", "doubtful")}), 1),
                mu=round(mu_fn(p, stat), 1), status=status))

def odds_lines(sport, markets):
    """Optional: median over-line across books from The Odds API. Needs ODDS_API_KEY."""
    res = {}
    if not ODDS_KEY: sources[f"odds_{sport}"] = "skipped (no ODDS_API_KEY)"; return res
    try:
        base = "https://api.the-odds-api.com/v4/sports/%s" % sport
        evs = get(base + "/events", params={"apiKey": ODDS_KEY}).json()
        tmp = {}
        for ev in evs:
            if dt.datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00")).date() > TODAY + dt.timedelta(days=3): continue
            o = get(f"{base}/events/{ev['id']}/odds", params={"apiKey": ODDS_KEY, "regions": "us", "markets": ",".join(markets), "oddsFormat": "american"}).json()
            for b in o.get("bookmakers", []):
                for m in b["markets"]:
                    for oc in m["outcomes"]:
                        if oc["name"] == "Over": tmp.setdefault((norm(oc["description"]), m["key"]), []).append(oc["point"])
        res = {k: st.median(v) for k, v in tmp.items()}
        sources[f"odds_{sport}"] = f"ok ({len(res)} lines)"
    except Exception as e:
        sources[f"odds_{sport}"] = f"failed: {e}"
    return res

def manual_lines():
    try:
        return {(norm(k.split("|")[0]), k.split("|")[1]): float(v) for k, v in json.load(open("lines.json")).items()}
    except Exception: return {}

# ---------------- NFL (nflverse) ----------------
NFL_MK = {"player_pass_yds": "Passing yards", "player_rush_yds": "Rushing yards", "player_reception_yds": "Receiving yards", "player_receptions": "Receptions"}
def nfl():
    base = "https://github.com/nflverse/nflverse-data/releases/download/"
    season = TODAY.year if TODAY.month >= 3 else TODAY.year - 1
    w = pd.concat([pd.read_csv(io.StringIO(get(f"{base}stats_player/stats_player_week_{s}.csv").text)) for s in (season - 1, season)])
    w = w[w.season_type == "REG"].sort_values(["season", "week"])
    g = pd.read_csv(io.StringIO(get(base + "schedules/games.csv").text))
    g = g[(g.season == season) & g.result.isna()].copy()
    g["d"] = pd.to_datetime(g.gameday).dt.date
    g = g[(g.d >= TODAY) & (g.d <= TODAY + dt.timedelta(days=int(os.environ.get("HORIZON_DAYS", 7))))]
    cur = w[w.season == season]
    ar = allowed_ratio(cur, "opponent_team", "game_id", ["passing_yards", "rushing_yards", "receiving_yards", "receptions"])
    games = {}
    for _, r in g.iterrows():
        fav = r.spread_line if pd.notna(r.spread_line) else 0; tot = r.total_line if pd.notna(r.total_line) else 45
        games[r.home_team] = dict(opp=r.away_team, home=1, gid=r.game_id, when=f"{r.gameday} {r.gametime}", fav=fav, tot=tot)
        games[r.away_team] = dict(opp=r.home_team, home=0, gid=r.game_id, when=f"{r.gameday} {r.gametime}", fav=-fav, tot=tot)
    inj = {}
    try:
        ij = pd.read_csv(io.StringIO(get(base + f"injuries/injuries_{season}.csv").text))
        ij = ij[ij.week == ij.week.max()]
        inj = {norm(n): str(sv) for n, sv in zip(ij.full_name, ij.report_status) if pd.notna(sv)}
        sources["injuries_nfl"] = f"ok (week {int(ij.week.max())}, {len(inj)} listed)"
    except Exception as e:
        sources["injuries_nfl"] = f"failed: {e}"
    lines = {**{(k[0], NFL_MK[k[1]]): v for k, v in odds_lines("americanfootball_nfl", list(NFL_MK)).items()}, **manual_lines()}
    last = w.groupby("player_id").tail(6)
    team_players = {}
    for pid, d in w.groupby("player_id"):
        d6 = d.tail(6); t = d6.team.iloc[-1]
        if t not in games or d6.season.iloc[-1] != season or d6.week.iloc[-1] < w[w.season == season].week.max() - 2: continue
        pos = d6.position.iloc[-1]; stats = {}
        if pos == "QB" and d.tail(2).attempts.mean() >= 20: stats["Passing yards"] = list(d.passing_yards)
        if pos == "RB" and d6.carries.mean() >= 8: stats["Rushing yards"] = list(d.rushing_yards)
        if pos in ("WR", "TE", "RB") and d6.targets.mean() >= (4 if pos != "RB" else 3):
            stats["Receiving yards"] = list(d.receiving_yards); stats["Receptions"] = list(d.receptions)
        if stats: team_players.setdefault(t, []).append(dict(name=d.player_display_name.iloc[-1], team=t, stats=stats, use=d6.targets.mean() + d6.carries.mean() + d6.attempts.mean() / 3, **games[t]))
    players = []
    for t, ps in team_players.items():
        qbs = sorted([p for p in ps if "Passing yards" in p["stats"]], key=lambda p: -p["use"])
        ps = [p for p in ps if "Passing yards" not in p["stats"]] + qbs[:1]
        top = sorted(ps, key=lambda p: -p["use"])[:7]
        for p in top: p["_team"] = ps
        players += top
    def mu(p, stat):
        opp_adj = ar[{"Passing yards": "passing_yards", "Rushing yards": "rushing_yards", "Receiving yards": "receiving_yards", "Receptions": "receptions"}[stat]].get(p["opp"], 0)
        if stat == "Rushing yards": script = 0.6 * p["fav"]                    # favorites run more late
        else: script = -0.4 * p["fav"] + (p["tot"] - 45) * 0.3                 # underdogs and shootouts throw more
        return max(-12, min(12, opp_adj + script))
    finish("NFL", players, inj, mu, lines)
    sources["nfl"] = f"ok ({len(players)} players, {len(g)} games)"

# ---------------- NBA (nba_api) ----------------
NBA_MK = {"player_points": "Points", "player_rebounds": "Rebounds", "player_assists": "Assists", "player_threes": "3-pointers made", "player_points_rebounds_assists": "Pts+Reb+Ast"}
def nba():
    from nba_api.stats.endpoints import leaguegamelog, scoreboardv2
    from nba_api.stats.static import teams
    y = TODAY.year if TODAY.month >= 10 else TODAY.year - 1
    seasons = [f"{y-1}-{str(y)[2:]}", f"{y}-{str(y+1)[2:]}"]
    df = pd.concat([leaguegamelog.LeagueGameLog(season=s, player_or_team_abbreviation="P", timeout=90).get_data_frames()[0] for s in seasons])
    df = df.sort_values("GAME_DATE"); df["OPP"] = df.MATCHUP.str.split().str[-1]
    df["PRA"] = df.PTS + df.REB + df.AST
    ids = {t["id"]: t["abbreviation"] for t in teams.get_teams()}
    games = {}
    for k in range(int(os.environ.get("HORIZON_NBA", 2)) + 1):
        d = TODAY + dt.timedelta(days=k)
        gh = scoreboardv2.ScoreboardV2(game_date=d.strftime("%m/%d/%Y"), timeout=90).get_data_frames()[0]
        for _, r in gh.iterrows():
            if r.GAME_STATUS_ID != 1: continue
            h, a = ids[r.HOME_TEAM_ID], ids[r.VISITOR_TEAM_ID]
            games[h] = dict(opp=a, home=1, gid=str(r.GAME_ID), when=str(d)); games[a] = dict(opp=h, home=0, gid=str(r.GAME_ID), when=str(d))
    cur = df[df.SEASON_ID.astype(str).str[-4:] == str(y)]
    ar = allowed_ratio(cur, "OPP", "GAME_ID", ["PTS", "REB", "AST", "FG3M", "PRA"])
    inj = injuries("basketball/nba")
    lines = {**{(k[0], NBA_MK[k[1]]): v for k, v in odds_lines("basketball_nba", list(NBA_MK)).items()}, **manual_lines()}
    team_players = {}
    for pid, d in df.groupby("PLAYER_ID"):
        d10 = d.tail(10); t = d10.TEAM_ABBREVIATION.iloc[-1]
        if t not in games or len(d) < 8 or d10.MIN.mean() < 22: continue
        stats = {"Points": list(d.PTS), "Rebounds": list(d.REB), "Assists": list(d.AST), "Pts+Reb+Ast": list(d.PRA)}
        if d10.FG3M.mean() >= 1: stats["3-pointers made"] = list(d.FG3M)
        team_players.setdefault(t, []).append(dict(name=d.PLAYER_NAME.iloc[-1], team=t, stats=stats, use=d10.MIN.mean(), **games[t]))
    players = []
    for t, ps in team_players.items():
        top = sorted(ps, key=lambda p: -p["use"])[:7]
        for p in top: p["_team"] = ps
        players += top
    col = {"Points": "PTS", "Rebounds": "REB", "Assists": "AST", "3-pointers made": "FG3M", "Pts+Reb+Ast": "PRA"}
    finish("NBA", players, inj, lambda p, s: ar[col[s]].get(p["opp"], 0) + (1 if p["home"] else -1), lines)
    sources["nba"] = f"ok ({len(players)} players, {len(games)//2} games)"

for name, fn in (("nfl", nfl), ("nba", nba)):
    try: fn()
    except Exception as e: sources[name] = f"failed: {type(e).__name__}: {e}"
json.dump(dict(generated=dt.datetime.now(dt.timezone.utc).isoformat(), asof=str(TODAY), sources=sources, rows=rows), open(OUT, "w"), separators=(",", ":"))
print(json.dumps(sources, indent=1)); print(len(rows), "rows ->", OUT)
