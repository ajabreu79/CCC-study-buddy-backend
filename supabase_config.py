import os
from dotenv import load_dotenv
from supabase import create_client, SupabaseException

# Load local .env in development
load_dotenv()

# Get Supabase keys
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise EnvironmentError(
        "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_ANON_KEY) must be set in the environment"
    )

# Strip whitespace just in case
SUPABASE_URL = SUPABASE_URL.strip()
SUPABASE_KEY = SUPABASE_KEY.strip()

# Create the Supabase client
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Fail-fast check: try fetching a single table to validate the key
try:
    # This doesn't matter which table, just a lightweight call to validate
    supabase.table("modules").select("id").limit(1).execute()
except SupabaseException as e:
    raise SupabaseException(
        "Supabase client initialization failed. Check your SUPABASE_KEY and SUPABASE_URL."
    ) from e

def table(name: str):
    """Helper to access a table: table("modules").select(...).execute()"""
    return supabase.table(name)
