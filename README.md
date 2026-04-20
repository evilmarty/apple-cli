# Apple CLIs

A collection of Python CLIs for controlling Apple applications through AppleScript (`osascript`). No dependency on third-party Python packages, just the standard library. Each CLI is self-contained and can be installed separately, but they share a common design and codebase for AppleScript interaction.

`mail-app` is a Python CLI that controls Apple Mail that can view and send messages.

`reminders-app` is a companion Python CLI for Apple Reminders with list/reminder management and query-based bulk actions.

`calendar-app` is a Python CLI for Apple Calendar to manage calendars and events.

`notes-app` is a Python CLI for Apple Notes to manage notes and folders.

`contacts-app` is a Python CLI for macOS Contacts to manage contacts and groups.

## Requirements

- macOS
- Python 3.9+

## Installation

To install the latest release from PyPI:

```bash
python3 -m pip install apple-cli
```

### Editable/Development Install

To install in editable mode for development:

```bash
git clone https://github.com/evilmarty/apple-cli.git
cd apple-cli
python3 -m pip install -e .
```

After installation, the following commands will be available in your PATH:
- `mail-app`
- `reminders-app`
- `calendar-app`
- `notes-app`
- `contacts-app`

## mail-app command overview

### Messages

```bash
mail-app messages list [--account ACCOUNT] [--mailbox MAILBOX] [--limit N] [--order desc|asc] [--json]
mail-app messages view (--id "<id>" | --message-id "<message-id>") [--account ACCOUNT] [--mailbox MAILBOX] [--body-only] [--json]
mail-app messages show (--id "<id>" | --message-id "<message-id>") [--account ACCOUNT] [--mailbox MAILBOX]
mail-app messages send --to TO [--to TO] --subject "Hello" --body "Hi there" [--cc CC] [--bcc BCC] [--account ACCOUNT]
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
reminders-app reminders show --id ID
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

## calendar-app command overview

### Events

```bash
calendar-app events list [--calendar CALENDAR] [--start-after DATE] [--start-before DATE] [--limit N] [--order desc|asc] [--json]
calendar-app events view --id ID [--json]
calendar-app events show --id ID
calendar-app events create --summary SUMMARY --start-date DATE (--end-date DATE | --duration DURATION) [--location LOC] [--notes TEXT] [--all-day] [--url URL] [--calendar CAL] [--alarm MIN]
calendar-app events update --id ID [--summary SUMMARY] [--start-date DATE] [--end-date DATE | --duration DURATION] [--location LOC] [--notes TEXT] [--all-day|--no-all-day] [--url URL] [--calendar CAL]
calendar-app events delete --id ID
```

- `events list` defaults to events starting from "now" if no date range is provided.
- `events list` output includes a human-friendly `duration` column (e.g., `15m`, `2h`, `1d`).
- `events create/update` `--duration` accepts human-friendly strings like `30m`, `3h`, `2d`.

### Calendars

```bash
calendar-app calendars list [--json]
calendar-app calendars create --name NAME
calendar-app calendars rename --calendar NAME --new-name NEW_NAME
calendar-app calendars delete --calendar NAME
```

## notes-app command overview

### Notes

```bash
notes-app notes list [--folder FOLDER] [--limit N] [--order desc|asc] [--json]
notes-app notes view --id ID [--json]
notes-app notes show --id ID
notes-app notes create --name NAME --body TEXT [--folder FOLDER]
notes-app notes update --id ID [--name NAME] [--body TEXT] [--folder FOLDER]
notes-app notes delete --id ID
```

### Folders

```bash
notes-app folders list [--json]
notes-app folders create --name NAME
notes-app folders delete --name NAME
```

## contacts-app command overview

### Contacts

```bash
contacts-app contacts list [--search TEXT] [--group GROUP] [--limit N] [--order desc|asc] [--json]
contacts-app contacts view --id ID [--json]
contacts-app contacts show --id ID
contacts-app contacts create --first-name NAME [--last-name NAME] [--organization ORG] [--job-title JOB] [--nickname NICK] [--note TEXT] [--email EMAIL] [--phone PHONE]
contacts-app contacts delete --id ID
```

### Groups

```bash
contacts-app groups list [--json]
contacts-app groups create --name NAME
contacts-app groups delete --name NAME
```

## Building from source

To build a wheel and source distribution:

1. Clone the repository:
   ```bash
   git clone https://github.com/evilmarty/apple-cli.git
   cd apple-cli
   ```

2. (Optional) Create and activate a virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. Run the build command:
   ```bash
   make build
   ```

The build artifacts will be available in the `dist/` directory.

## Testing

The project uses the standard library `unittest` framework.

To run all tests:
```bash
make test
```

To run tests for a specific application:
```bash
PYTHONPATH=src python3 -m unittest tests/test_calendar_app.py
```

Tests use mocking extensively to avoid actually executing AppleScripts that would interact with your native apps, making them safe to run in any environment.

## Contributing

Contributions are welcome! If you'd like to contribute:

1. **Report Bugs or Request Features:** Open an issue on [GitHub](https://github.com/evilmarty/apple-cli/issues).
2. **Submit Pull Requests:**
   - Fork the repository.
   - Create a new branch for your feature or fix.
   - Ensure your code follows the existing style and is well-documented.
   - **Important:** Add tests for any new functionality or bug fixes.
   - Run the full test suite (`make test`) before submitting.
3. **Coding Standards:**
   - Use type hints for all function signatures.
   - Keep the codebase compatible with Python 3.9+.
   - Maintain the zero-dependency goal (use only the Python standard library).
