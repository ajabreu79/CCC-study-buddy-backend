import os
from dotenv import load_dotenv
from supabase import create_client, SupabaseException

# Load local .env in development
load_dotenv()

def _norm(val: str | None) -> str:
    return (val or "").strip()


SUPABASE_URL = _norm(os.getenv("SUPABASE_URL"))
SUPABASE_SERVICE_ROLE_KEY = _norm(os.getenv("SUPABASE_SERVICE_ROLE_KEY"))
SUPABASE_ANON_KEY = _norm(os.getenv("SUPABASE_ANON_KEY"))

if not SUPABASE_URL:
    raise EnvironmentError("Missing `SUPABASE_URL` (required for Supabase).")

if not SUPABASE_SERVICE_ROLE_KEY and not SUPABASE_ANON_KEY:
    raise EnvironmentError(
        "Missing Supabase keys: set `SUPABASE_SERVICE_ROLE_KEY` and/or `SUPABASE_ANON_KEY`."
    )


# Try service role first (server-side), then fall back to anon key.
key_candidates: list[tuple[str, str]] = []
if SUPABASE_SERVICE_ROLE_KEY:
    key_candidates.append(("service_role", SUPABASE_SERVICE_ROLE_KEY))
if SUPABASE_ANON_KEY:
    key_candidates.append(("anon", SUPABASE_ANON_KEY))

supabase = None
last_error: SupabaseException | None = None

# Extra validation (a test query) can be expensive and can fail due to RLS.
# Keep it OFF by default so the backend can still start if Supabase is only needed later.
validate = os.getenv("SUPABASE_VALIDATE", "0").lower() in ("1", "true", "yes")

for label, key in key_candidates:
    try:
        supabase = create_client(SUPABASE_URL, key)

        if validate:
            # This doesn't matter which table, just a lightweight call to validate.
            supabase.table("modules").select("id").limit(1).execute()
        break
    except SupabaseException as e:
        last_error = e
        supabase = None

if supabase is None:
    tried = ", ".join([label for (label, _) in key_candidates])
    raise SupabaseException(
        "Supabase client initialization failed (invalid API key or connectivity issue). "
        f"Tried: {tried}. "
        "Make sure your `SUPABASE_SERVICE_ROLE_KEY` / `SUPABASE_ANON_KEY` are real Supabase JWT keys "
        "(they should start with `eyJ...`). "
        f"Last error: {last_error}"
    )

def table(name: str):
    """Helper to access a table: table("modules").select(...).execute()"""
    return supabase.table(name)
