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
