SET statement_timeout = '30s';

REVOKE EXECUTE ON FUNCTION public.get_canonical_politician_summaries(text, integer, integer) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.get_covoting(uuid) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION public.get_canonical_politician_summaries(text, integer, integer) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_covoting(uuid) TO anon, authenticated;

NOTIFY pgrst, 'reload schema';
