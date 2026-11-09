-- Read-only functions the website calls (Supabase RPC). SECURITY DEFINER so the
-- anon key can read the edge history through them without table access.

CREATE OR REPLACE FUNCTION public.edge_horse_runs(p_name text)
RETURNS TABLE (race_date text, track text, state text, distance integer, class_band text, going text,
               finish_pos integer, field_size integer, margin double precision, weight double precision,
               barrier integer, jockey text, settle_pos integer, pos_800 integer, pos_400 integer,
               sp double precision, bsp double precision, wfa_rating double precision,
               race_in_prep integer, days_since_prev integer, stewards_comment text, race_name text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = edge, public AS $$
  SELECT ra.race_date, ra.track, ra.state, ra.distance, ra.class_band, ra.going,
         r.finish_pos, COALESCE(r.field_size, ra.field_size), r.margin, r.weight, r.barrier, r.jockey,
         r.settle_pos, r.pos_800, r.pos_400, r.sp, r.bsp, NULLIF(r.wfa_rating, 0), r.race_in_prep,
         r.days_since_prev, r.stewards_comment, ra.race_name
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
