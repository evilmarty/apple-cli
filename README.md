# Apple CLIs

A collection of Python CLIs for controlling Apple applications through AppleScript (`osascript`). No dependency on third-party Python packages, just the standard library. Each CLI is self-contained and can be installed separately, but they share a common design and codebase for AppleScript interaction.

`mail-app` is a Python CLI that controls Apple Mail that can view and send messages.

`reminders-app` is a companion Python CLI for Apple Reminders with list/reminder management and query-based bulk actions.

## Requirements

- macOS
- Python 3.9+

## Install (editable/development)

```bash
python3 -m pip install -e .
```

Then run:

```bash
mail-app --help
```

## mail-app command overview

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

## reminders-app command overview

### Reminders

```bash
reminders-app reminders list [--list LIST] [--limit N] [--order desc|asc] [--completed|--all] [--json]
reminders-app reminders view --id ID [--body-only] [--json]
reminders-app reminders create --title TITLE [--notes TEXT] [--list LIST] [--due-date DATE] [--priority N]
reminders-app reminders update --id ID [--title TITLE] [--notes TEXT] [--due-date DATE] [--priority N] [--list LIST]
reminders-app reminders complete [--id ID | selectors | --all]
reminders-app reminders uncomplete [--id ID | selectors | --all]
reminders-app reminders delete [--id ID | selectors | --all]
reminders-app reminders move --destination-list LIST [--id ID | selectors | --all]
```

### Lists

```bash
reminders-app lists list [--json]
reminders-app lists create --name NAME
reminders-app lists rename --list NAME --new-name NEW_NAME
reminders-app lists delete --list NAME
```

### Note on Performance

Due to inefficiencies in how the Apple Reminders application handles bulk queries and property retrieval through AppleScript, some commands (especially `list` when querying many items) may experience delays or timeouts. If you encounter timeouts, try narrowing the scope of your command by specifying a `--list`.
