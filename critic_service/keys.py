"""Generate a critic service API key.

The key goes to the orchestrator as CRITIC_API_KEY; only its hash goes to the critic
service as CRITIC_API_KEY_SHA256.
"""

from auth.api_keys import generate_key, hash_key


def main() -> None:
    key = generate_key()
    print(f"CRITIC_API_KEY={key}")
    print(f"CRITIC_API_KEY_SHA256={hash_key(key)}")


if __name__ == "__main__":
    main()
