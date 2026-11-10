CREATE TABLE IF NOT EXISTS edge.model_params (name TEXT PRIMARY KEY, fitted_at TEXT, params_json TEXT);

-- Blackbook: horses the syndicate is following. Read with the public key; written
-- only by the Netlify function (service key).
CREATE TABLE IF NOT EXISTS public.edge_blackbook (
  horse_name TEXT PRIMARY KEY, note TEXT, added_by TEXT, created_at TEXT, source TEXT, removed INTEGER DEFAULT 0);
ALTER TABLE public.edge_blackbook ENABLE ROW LEVEL SECURITY;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.edge_blackbook FROM anon, authenticated;
GRANT SELECT ON public.edge_blackbook TO anon, authenticated;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname = 'public' AND tablename = 'edge_blackbook'
  AND policyname = 'site can read') THEN
  CREATE POLICY "site can read" ON public.edge_blackbook FOR SELECT TO anon, authenticated USING (true); END IF; END $$;

-- Bet log. The site reads it with the public key; only the Netlify function
-- (service key, PIN-protected) can add or void bets.
CREATE TABLE IF NOT EXISTS public.edge_bets (
  id TEXT PRIMARY KEY, created_at TEXT, bettor TEXT, meeting_date TEXT, track TEXT,
  race_id TEXT, race_number INTEGER, horse_name TEXT, saddlecloth INTEGER,
  odds_taken DOUBLE PRECISION, stake DOUBLE PRECISION, to_win DOUBLE PRECISION,
  fair_price DOUBLE PRECISION, edge_pct DOUBLE PRECISION, bookmaker TEXT, note TEXT,
  void INTEGER DEFAULT 0);
ALTER TABLE public.edge_bets ENABLE ROW LEVEL SECURITY;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.edge_bets FROM anon, authenticated;
GRANT SELECT ON public.edge_bets TO anon, authenticated;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname = 'public' AND tablename = 'edge_bets'
  AND policyname = 'site can read') THEN
  CREATE POLICY "site can read" ON public.edge_bets FOR SELECT TO anon, authenticated USING (true); END IF; END $$;

-- Read-only functions the website calls (Supabase RPC). SECURITY DEFINER so the
-- anon key can read the edge history through them without table access.

-- Columns changed (race_id and winners-out-of-the-race added), so drop first.
DROP FUNCTION IF EXISTS public.edge_horse_runs(text);
CREATE OR REPLACE FUNCTION public.edge_horse_runs(p_name text)
RETURNS TABLE (race_date text, track text, state text, distance integer, class_band text, going text,
               finish_pos integer, field_size integer, margin double precision, weight double precision,
               barrier integer, jockey text, settle_pos integer, pos_800 integer, pos_400 integer,
               sp double precision, bsp double precision, wfa_rating double precision,
               race_in_prep integer, days_since_prev integer, stewards_comment text, race_name text,
               race_id text, next_runs integer, next_wins integer)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = edge, public AS $$
  SELECT ra.race_date, ra.track, ra.state, ra.distance, ra.class_band, ra.going,
         r.finish_pos, COALESCE(r.field_size, ra.field_size), r.margin, r.weight, r.barrier, r.jockey,
         r.settle_pos, r.pos_800, r.pos_400, r.sp, r.bsp, NULLIF(r.wfa_rating, 0), r.race_in_prep,
         r.days_since_prev, r.stewards_comment, ra.race_name, r.race_id, r.next_runs, r.next_wins
  FROM edge.runs r JOIN edge.races ra USING (race_id)
  WHERE lower(r.horse_name) = lower(p_name) AND r.finish_pos IS NOT NULL
  ORDER BY ra.race_date DESC
  LIMIT 60
$$;

CREATE OR REPLACE FUNCTION public.edge_horse_search(q text)
RETURNS TABLE (horse_name text, runs bigint, last_run text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = edge, public AS $$
  SELECT r.horse_name, count(*), max(ra.race_date)
  FROM edge.runs r JOIN edge.races ra USING (race_id)
  WHERE length(q) >= 2 AND r.horse_name ILIKE '%' || q || '%'
  GROUP BY r.horse_name
  ORDER BY (lower(r.horse_name) LIKE lower(q) || '%') DESC, max(ra.race_date) DESC
  LIMIT 15
$$;

-- Pattern Lab: actual wins vs the wins the starting price expected (A/E), per
-- angle, split into an older and a recent half so an angle has to hold up twice.
-- Baseline A/E is shown per half; survivorship (history only holds horses still
-- racing) lifts every A/E, so judge an angle by its ratio to the baseline.
CREATE OR REPLACE FUNCTION public.edge_angle_stats(p_split text DEFAULT '2026-05-01')
RETURNS TABLE (angle text, side text, n_old bigint, ae_old numeric, n_recent bigint, ae_recent numeric,
               strike numeric, roi_sp numeric)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = edge, public AS $$
  WITH h AS (
    SELECT ra.race_date, ra.distance, r.finish_pos, r.margin, r.sp, r.race_in_prep, r.days_since_prev,
           lag(r.finish_pos) OVER w lf, lag(r.margin) OVER w lm, lag(r.settle_pos) OVER w lset,
           lag(r.pos_800) OVER w l800, lag(r.stewards_comment) OVER w lstew, lag(ra.distance) OVER w ldist
    FROM edge.runs r JOIN edge.races ra USING (race_id)
    WINDOW w AS (PARTITION BY r.horse_name ORDER BY ra.race_date)
  ), b AS (
    SELECT *, (finish_pos = 1)::int win, race_date >= p_split recent FROM h WHERE sp > 1 AND finish_pos IS NOT NULL
  ), t AS (
    SELECT 'Baseline (every run)' angle, '' side, * FROM b
    UNION ALL SELECT 'Won last start', 'back', * FROM b WHERE lf = 1
    UNION ALL SELECT 'Led and won last start', 'back', * FROM b WHERE lf = 1 AND lset = 1
    UNION ALL SELECT 'Up 200m+ in trip', 'back', * FROM b WHERE distance - ldist >= 200
    UNION ALL SELECT 'Priced $3 to $6', 'back', * FROM b WHERE sp >= 3 AND sp < 6
    UNION ALL SELECT '2nd-up', 'neutral', * FROM b WHERE race_in_prep = 2
    UNION ALL SELECT '1st-up', 'neutral', * FROM b WHERE race_in_prep = 1
    UNION ALL SELECT 'Made 5+ spots from the 800m last start', 'neutral', * FROM b WHERE l800 - lf >= 5
    UNION ALL SELECT 'Hard-luck excuse last start (stewards)', 'fade', * FROM b
      WHERE lstew ~* '(held up|checked|blocked|crowded|bumped|hampered|steadied|shoe|slow(ly)? (away|to begin)|missed the start|without cover|no clear run|clipped heels|eased|awkwardly)'
    UNION ALL SELECT 'Beaten 1L or less last start', 'fade', * FROM b WHERE lf > 1 AND lm >= -1
    UNION ALL SELECT 'Down 200m+ in trip', 'fade', * FROM b WHERE ldist - distance >= 200
    UNION ALL SELECT 'Priced $25+', 'fade', * FROM b WHERE sp >= 25
  )
  SELECT angle, side,
         count(*) FILTER (WHERE NOT recent),
         round((sum(win) FILTER (WHERE NOT recent))::numeric / NULLIF(sum(1 / sp) FILTER (WHERE NOT recent), 0)::numeric, 3),
         count(*) FILTER (WHERE recent),
         round((sum(win) FILTER (WHERE recent))::numeric / NULLIF(sum(1 / sp) FILTER (WHERE recent), 0)::numeric, 3),
         round(avg(win)::numeric * 100, 1),
         round((sum(CASE WHEN win = 1 THEN sp - 1 ELSE -1 END) / count(*) * 100)::numeric, 1)
  FROM t GROUP BY angle, side
$$;

GRANT EXECUTE ON FUNCTION public.edge_horse_runs(text) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION public.edge_horse_search(text) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION public.edge_angle_stats(text) TO anon, authenticated;

-- Track & barriers: how winners are spread by barrier and by where they settled,
-- at one track over a distance range (optionally one going band / rail type).
-- Impact value (IV) = winners from a group / winners expected if every gate or
-- position had the same chance (its share of the field). 1.0 = fair, 1.3 = 30%
-- more winners than its share, 0.7 = 30% fewer. Uses winners only, so it is not
-- skewed by which losers happen to be in the history.
CREATE OR REPLACE FUNCTION public.edge_track_stats(p_track text, p_dmin integer, p_dmax integer,
                                                   p_going text DEFAULT NULL, p_rail text DEFAULT NULL)
RETURNS TABLE (dim text, bucket text, sort_key integer, races bigint, wins bigint, expected numeric, iv numeric)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = edge, public AS $$
  WITH fs AS (
    -- Field size when the winner's own row lacks it: another runner's record of
    -- the same race, else the widest barrier we saw in it.
    SELECT r.race_id, max(r.field_size) AS fs, max(r.barrier) AS bar
    FROM edge.runs r JOIN edge.races ra USING (race_id)
    WHERE lower(ra.track) = lower(p_track) AND ra.distance BETWEEN p_dmin AND p_dmax
    GROUP BY r.race_id
  ), w0 AS (
    SELECT r.barrier, COALESCE(r.field_size, ra.field_size, fs.fs, fs.bar) AS n, r.settle_pos AS s, ra.rail
    FROM edge.runs r JOIN edge.races ra USING (race_id) JOIN fs USING (race_id)
    WHERE r.finish_pos = 1 AND lower(ra.track) = lower(p_track)
      AND ra.distance BETWEEN p_dmin AND p_dmax
      AND r.barrier IS NOT NULL AND r.barrier > 0
      AND (p_going IS NULL
           OR (p_going = 'Good' AND ra.going ~* '^(good|firm|dead|fast)')
           OR (p_going = 'Soft' AND ra.going ~* '^(soft|slow)')
           OR (p_going = 'Heavy' AND ra.going ~* '^heavy')
           OR (p_going = 'Synthetic' AND ra.going ~* 'synth'))
      AND (p_rail IS NULL
           OR (p_rail = 'True' AND ra.rail ~* '^true')
           OR (p_rail = 'Out' AND ra.rail IS NOT NULL AND ra.rail !~* '^true'))
  ), w AS (
    SELECT LEAST(barrier, n) AS b, n, s, rail FROM w0 WHERE n >= 5
  ), z AS (
    SELECT *, CASE WHEN s = 1 THEN 1 WHEN s <= 3 THEN 2 WHEN s <= ceil(n * 0.6) THEN 3 ELSE 4 END AS zone,
           GREATEST(ceil(n * 0.6)::int, 3) AS mid_hi
    FROM w WHERE s IS NOT NULL AND s > 0 AND s <= n
  ), g(name, lo, hi, k) AS (
    VALUES ('Inside (1-3)', 1, 3, 1), ('Middle (4-7)', 4, 7, 2), ('Outside (8-11)', 8, 11, 3), ('Wide (12+)', 12, 99, 4)
  ), zn(name, k) AS (
    VALUES ('Led', 1), ('On speed (2nd-3rd)', 2), ('Midfield', 3), ('Back half', 4)
  ), bar AS (
    SELECT 'barrier'::text AS dim, gs::text AS bucket, gs AS sort_key,
           (SELECT count(*) FROM w) AS races, (SELECT count(*) FROM w WHERE w.b = gs) AS wins,
           (SELECT sum(CASE WHEN gs <= w.n THEN 1.0 / w.n ELSE 0 END) FROM w)::numeric AS expected
    FROM generate_series(1, 16) gs
  ), grp AS (
    SELECT 'group'::text, g.name, g.k,
           (SELECT count(*) FROM w), (SELECT count(*) FROM w WHERE w.b BETWEEN g.lo AND g.hi),
           (SELECT sum(GREATEST(0, LEAST(g.hi, w.n) - g.lo + 1)::numeric / w.n) FROM w)
    FROM g
  ), stl AS (
    SELECT 'settle'::text, zn.name, zn.k,
           (SELECT count(*) FROM z), (SELECT count(*) FROM z WHERE z.zone = zn.k),
           (SELECT sum(CASE zn.k WHEN 1 THEN 1 WHEN 2 THEN 2 WHEN 3 THEN z.mid_hi - 3 ELSE z.n - z.mid_hi END::numeric / z.n) FROM z)
    FROM zn
  ), meta AS (
    SELECT 'meta'::text, 'rail recorded'::text, 0, (SELECT count(*) FROM w), (SELECT count(*) FROM w WHERE w.rail IS NOT NULL), NULL::numeric
  ), u AS (
    SELECT * FROM bar UNION ALL SELECT * FROM grp UNION ALL SELECT * FROM stl UNION ALL SELECT * FROM meta
  )
  SELECT u.dim, u.bucket, u.sort_key, u.races, u.wins, round(u.expected, 2),
         CASE WHEN u.expected > 0 THEN round(u.wins / u.expected, 2) END
  FROM u
$$;

GRANT EXECUTE ON FUNCTION public.edge_track_stats(text, integer, integer, text, text) TO anon, authenticated;

-- Meeting Review: what the history holds for a set of races (in-run positions,
-- the Form King rating and stewards report arrive here as each runner's later
-- cards are pulled; finish/margins/prices land on the night of the race).
CREATE OR REPLACE FUNCTION public.edge_race_runs(p_race_ids text[])
RETURNS TABLE (race_id text, horse_name text, finish_pos integer, margin double precision,
               wfa_rating double precision, settle_pos integer, pos_800 integer, pos_400 integer,
               field_size integer, sp double precision, bsp double precision, stewards_comment text, source text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = edge, public AS $$
  SELECT r.race_id, r.horse_name, r.finish_pos, r.margin, NULLIF(r.wfa_rating, 0), r.settle_pos, r.pos_800,
         r.pos_400, r.field_size, r.sp, r.bsp, r.stewards_comment, r.source
  FROM edge.runs r
  WHERE r.race_id = ANY (p_race_ids)
$$;

GRANT EXECUTE ON FUNCTION public.edge_race_runs(text[]) TO anon, authenticated;


-- The fitted model's report (Pattern Lab shows it).
CREATE OR REPLACE FUNCTION public.edge_model_report(p_name text DEFAULT 'v2')
RETURNS TABLE (name text, fitted_at text, params_json text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = edge, public AS $$
  SELECT name, fitted_at, params_json FROM edge.model_params WHERE name = p_name
$$;

GRANT EXECUTE ON FUNCTION public.edge_model_report(text) TO anon, authenticated;


-- One past race in full: the header plus every runner we hold, so a last-start
-- line on a card can open the race it came out of.
CREATE OR REPLACE FUNCTION public.edge_past_race(p_race_id text)
RETURNS TABLE (race_id text, meeting_id text, race_date text, track text, state text,
               race_number integer, race_name text, distance integer, restrictions text,
               going text, rail text, prize_money double precision, field_size integer,
               horse_name text, runner_number integer, barrier integer, weight double precision,
               jockey text, finish_pos integer, margin double precision, wfa_rating double precision,
               settle_pos integer, pos_800 integer, pos_400 integer, sp double precision,
               bsp double precision, stewards_comment text, gear text, race_in_prep integer,
               days_since_prev integer, next_runs integer, next_wins integer, source text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = edge, public AS $$
  SELECT rc.race_id, rc.meeting_id, rc.race_date, rc.track, rc.state, rc.race_number, rc.race_name,
         rc.distance, rc.restrictions, rc.going, rc.rail, rc.prize_money,
         COALESCE(rc.field_size, MAX(r.field_size) OVER ()),
         r.horse_name, r.runner_number, r.barrier, r.weight, r.jockey, r.finish_pos, r.margin,
         NULLIF(r.wfa_rating, 0), r.settle_pos, r.pos_800, r.pos_400, r.sp, r.bsp,
         r.stewards_comment, r.gear, r.race_in_prep, r.days_since_prev, r.next_runs, r.next_wins, r.source
  FROM edge.races rc
  LEFT JOIN edge.runs r ON r.race_id = rc.race_id
  WHERE rc.race_id = p_race_id
  ORDER BY r.finish_pos NULLS LAST, r.runner_number
$$;

GRANT EXECUTE ON FUNCTION public.edge_past_race(text) TO anon, authenticated;


-- How a track has been playing lately: every winner at that track in the last
-- N days with its barrier, where it settled, the going and the rail. The site
-- turns this into "leaders are winning here" / "wide draws are no good".
CREATE OR REPLACE FUNCTION public.edge_track_recent(p_track text, p_days integer DEFAULT 60)
RETURNS TABLE (race_date text, meeting_id text, race_id text, distance integer, going text, rail text,
               horse_name text, barrier integer, field_size integer, settle_pos integer,
               pos_800 integer, pos_400 integer, sp double precision, wfa_rating double precision)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = edge, public AS $$
  WITH fs AS (
    SELECT r.race_id, max(r.field_size) AS fs, max(r.barrier) AS bar
    FROM edge.runs r JOIN edge.races ra USING (race_id)
    WHERE lower(ra.track) = lower(p_track) AND ra.race_date >= to_char(current_date - p_days, 'YYYY-MM-DD')
    GROUP BY r.race_id
  )
  SELECT ra.race_date, ra.meeting_id, ra.race_id, ra.distance, ra.going, ra.rail,
         r.horse_name, r.barrier, COALESCE(r.field_size, ra.field_size, fs.fs, fs.bar),
         r.settle_pos, r.pos_800, r.pos_400, r.sp, NULLIF(r.wfa_rating, 0)
  FROM edge.runs r JOIN edge.races ra USING (race_id) JOIN fs USING (race_id)
  WHERE r.finish_pos = 1 AND lower(ra.track) = lower(p_track)
    AND ra.race_date >= to_char(current_date - p_days, 'YYYY-MM-DD')
  ORDER BY ra.race_date DESC, ra.race_number
$$;

GRANT EXECUTE ON FUNCTION public.edge_track_recent(text, integer) TO anon, authenticated;
