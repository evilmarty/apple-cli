# mail-app

`mail-app` is a Python CLI that controls Apple Mail through AppleScript (`osascript`).

## Requirements

- macOS with Apple Mail configured
- Python 3.13+
- Mail automation permission granted to your terminal when prompted

## Install (editable/development)

```bash
python3 -m pip install -e .
```

Then run:

```bash
mail-app --help
```

## Command overview

Aliases:
- `messages`: `msgs`, `msg`
- `mailboxes`: `mbox`, `mboxs`, `mboxes`
- `list`: `ls`
- `view`: `v`
- mailbox `delete`: `remove`, `rm`

### Messages

```bash
mail-app messages list [--account ACCOUNT] [--mailbox MAILBOX] [--limit N] [--order desc|asc] [--json]
mail-app messages view (--id "<id>" | --message-id "<message-id>") [--account ACCOUNT] [--mailbox MAILBOX] [--body-only] [--json]
mail-app messages send --to "a@example.com,b@example.com" --subject "Hello" --body "Hi there" [--cc ...] [--bcc ...] [--account ACCOUNT]
mail-app messages move (--id "<id>" | --message-id "<message-id>") --destination-mailbox DEST [--account ACCOUNT] [--source-mailbox MAILBOX]
mail-app messages archive (--id "<id>" | --message-id "<message-id>") [--account ACCOUNT] [--mailbox MAILBOX]
mail-app messages trash (--id "<id>" | --message-id "<message-id>") [--account ACCOUNT] [--mailbox MAILBOX]
mail-app messages spam (--id "<id>" | --message-id "<message-id>") [--account ACCOUNT] [--mailbox MAILBOX]
```

### Mailboxes

```bash
mail-app mailboxes list [--account ACCOUNT] [--json]
mail-app mailboxes create --account ACCOUNT --name NAME [--parent-mailbox MAILBOX]
mail-app mailboxes rename --account ACCOUNT --mailbox MAILBOX --new-name NEW_NAME
mail-app mailboxes delete --account ACCOUNT --mailbox MAILBOX
```

## Behavior notes

- `messages list` defaults to each account's Inbox, newest-first (`--order desc`), and returns the newest 100 messages unless overridden.
- `--mailbox` options require `--account` for deterministic mailbox resolution.
- Message-targeting commands accept either `--id` or `--message-id` (mutually exclusive).
- `messages view` uses `date` as the date field name.
- `messages view --body-only` prints only the message body.
- Plain text output hides the RFC `message_id` field; JSON output (`--json`) includes it.
- Mailboxes are represented as slash-delimited paths (example: `Projects/2026`).
- `archive` and `spam` move to `Archive` and `Junk` mailbox paths for the selected account.
