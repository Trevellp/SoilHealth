import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")


def get_supabase_client():
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("Missing SUPABASE_URL or SUPABASE_KEY in .env")

    return create_client(SUPABASE_URL, SUPABASE_KEY)


supabase = get_supabase_client()


def sign_up_user(email, password):
    return supabase.auth.sign_up({
        "email": email,
        "password": password,
    })


def sign_in_user(email, password):
    return supabase.auth.sign_in_with_password({
        "email": email,
        "password": password,
    })


def sign_out_user():
    return supabase.auth.sign_out()