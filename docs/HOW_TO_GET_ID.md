## Getting Telegram IDs (Draft)

- Chat ID:
  - Use Telethon to print `event.chat_id` in handlers.
  - For public channels/groups, you can also pass the username string (e.g., `@channelname`) to Telethon.

- Your own user ID:
  - After onboarding (`scripts/onboard_account.py`), run a small Telethon snippet to print `me.id`.

We will add more comprehensive instructions and tooling later.
