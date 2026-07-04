SET statement_timeout = '30s';

REVOKE EXECUTE ON FUNCTION public.get_covoting(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.get_covoting(uuid) TO anon, authenticated;

NOTIFY pgrst, 'reload schema';
