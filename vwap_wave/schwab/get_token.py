import os
from schwab import auth

if __name__ == "__main__":
    api_key = os.environ["SCHWAB_KEY"]
    app_secret = os.environ["SCHWAB_SECRET"]
    client = auth.client_from_manual_flow(
        token_path="./token.json",
        api_key=api_key,
        app_secret=app_secret,
        callback_url="https://127.0.0.1:8100",
    )
