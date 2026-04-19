from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any, Sequence

try:
    from version import __version__
except ImportError:
    __version__ = "unknown"


DEFAULT_LIST_LIMIT = 100
MISSING_VALUE = "missing value"

MESSAGE_DISPLAY_LABELS = {
    "id": "id",
    "subject": "subject",
    "sender": "sender",
    "date": "date",
    "account": "account",
    "mailbox": "mailbox"
}

ACTION_ALIASES = {"archive": ["arch"], "trash": ["delete", "rm"], "spam": ["junk"]}


class AppleMailError(RuntimeError):
    pass


class SubcommandHelpFormatter(argparse.HelpFormatter):
    def _format_action(self, action):
        if isinstance(action, argparse._SubParsersAction):
            parts = []
            for subaction in self._iter_indented_subactions(action):
                parts.append(self._format_action(subaction))
            return "".join(parts)
        return super()._format_action(action)


def run_osascript(script: str, args: Sequence[str]) -> str:
    result = subprocess.run(
        ["osascript", "-s", "h", "-", *args],
        input=script,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        detail = stderr or stdout or f"osascript exited with code {result.returncode}"
        raise AppleMailError(detail)
    return result.stdout.rstrip("\n")


def parse_tsv(output: str, field_names: Sequence[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if not output.strip():
        return rows
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) != len(field_names):
            raise AppleMailError("Unexpected AppleScript output format")
        rows.append(dict(zip(field_names, parts)))
    return rows


def print_rows(
    rows: Sequence[dict[str, Any]],
    as_json: bool,
    columns: list[str] | None = None,
    print_headers: bool = True,
) -> None:
    if as_json:
        if columns:
            rows = [{k: v for k, v in row.items() if k in columns} for row in rows]
        print(json.dumps(list(rows), ensure_ascii=False, indent=2))
        return
    if not rows:
        return
    
    headers = columns if columns else [key for key in rows[0].keys() if key != "message_id"]
    if print_headers:
        print("\t".join(headers))
    for row in rows:
        print("\t".join(str(row.get(header, "")) for header in headers))


def require_account_if_mailbox(account: str, mailbox: str, parser: argparse.ArgumentParser) -> None:
    if mailbox and not account:
        parser.error("--mailbox requires --account")


def add_message_selector_arguments(parser: argparse.ArgumentParser) -> None:
    selector_group = parser.add_mutually_exclusive_group(required=True)
    selector_group.add_argument("--id", help="Apple Mail message id")
    selector_group.add_argument("--message-id", help="RFC Message-ID header value")


def script_helpers() -> str:
    return """
on splitByDelimiter(valueText, delim)
    if valueText is "" then
        return {}
    end if
    set oldDelims to AppleScript's text item delimiters
    set AppleScript's text item delimiters to delim
    set parsedItems to text items of valueText
    set AppleScript's text item delimiters to oldDelims
    return parsedItems
end splitByDelimiter

on sanitize(value)
    if value is missing value then
        return ""
    end if
    set valueText to value as text
    set oldDelims to AppleScript's text item delimiters
    set AppleScript's text item delimiters to return
    set valueParts to text items of valueText
    set AppleScript's text item delimiters to " "
    set valueText to valueParts as text
    set AppleScript's text item delimiters to linefeed
    set valueParts to text items of valueText
    set AppleScript's text item delimiters to " "
    set valueText to valueParts as text
    set AppleScript's text item delimiters to tab
    set valueParts to text items of valueText
    set AppleScript's text item delimiters to " "
    set valueText to valueParts as text
    set AppleScript's text item delimiters to oldDelims
    return valueText
end sanitize

on trimValue(valueText)
    set sourceText to valueText as text
    repeat while sourceText begins with " "
        set sourceText to text 2 thru -1 of sourceText
    end repeat
    repeat while sourceText ends with " "
        set sourceText to text 1 thru -2 of sourceText
    end repeat
    return sourceText
end trimValue

on mailboxPath(mailboxRef)
    tell application "Mail"
        try
            set parentContainer to container of mailboxRef
            if class of parentContainer is account then
                return name of mailboxRef
            end if
            return my mailboxPath(parentContainer) & "/" & name of mailboxRef
        on error
            return name of mailboxRef
        end try
    end tell
end mailboxPath

on mailboxByPath(accountRef, mailboxPathText)
    set parts to my splitByDelimiter(mailboxPathText, "/")
    set currentRef to accountRef
    repeat with partRef in parts
        set currentRef to mailbox (contents of partRef) of currentRef
    end repeat
    return currentRef
end mailboxByPath

on emitRow(existingOutput, rowText)
    if existingOutput is "" then
        return rowText
    end if
    return existingOutput & linefeed & rowText
end emitRow
"""


def list_mailboxes(account: str) -> list[dict[str, str]]:
    script = (
        script_helpers()
        + """
on run argv
    set accountName to item 1 of argv
    set outText to ""
    tell application "Mail"
        if accountName is "" then
            set targetAccounts to every account
        else
            set targetAccounts to {account accountName}
        end if
        repeat with accountRef in targetAccounts
            set accountLabel to name of accountRef
            repeat with mailboxRef in every mailbox of accountRef
                set rowText to accountLabel & tab & my mailboxPath(mailboxRef)
                set outText to my emitRow(outText, rowText)
            end repeat
        end repeat
    end tell
    return outText
end run
"""
    )
    output = run_osascript(script, [account])
    return parse_tsv(output, ["account", "mailbox"])


def list_messages(account: str, mailbox: str, limit: int, order: str) -> list[dict[str, str]]:
    script = (
        script_helpers()
        + """
on run argv
    set accountName to item 1 of argv
    set mailboxName to item 2 of argv
    set maxCount to item 3 of argv as integer
    set sortOrder to item 4 of argv
    set remainingCount to maxCount
    set outText to ""

    tell application "Mail"
        if accountName is "" then
            set targetAccounts to every account
        else
            set targetAccounts to {account accountName}
        end if

        repeat with accountRef in targetAccounts
            if remainingCount is less than or equal to 0 then
                exit repeat
            end if

            set accountLabel to name of accountRef
            if mailboxName is "" then
                set targetMailboxes to {mailbox "INBOX" of accountRef}
            else
                set targetMailboxes to {my mailboxByPath(accountRef, mailboxName)}
            end if

            repeat with mailboxRef in targetMailboxes
                if remainingCount is less than or equal to 0 then
                    exit repeat
                end if

                set mailboxLabel to my mailboxPath(mailboxRef)
                set mailboxMessages to messages of mailboxRef
                set messageCount to count of mailboxMessages
                if sortOrder is "asc" then
                    repeat with msgIndex from 1 to messageCount by 1
                        if remainingCount is less than or equal to 0 then
                            exit repeat
                        end if
                        set messageRef to item msgIndex of mailboxMessages
                        set rowText to (id of messageRef as text) & tab & my sanitize(message id of messageRef) & tab & my sanitize(subject of messageRef) & tab & my sanitize(sender of messageRef) & tab & my sanitize(date received of messageRef as text) & tab & accountLabel & tab & mailboxLabel
                        set outText to my emitRow(outText, rowText)
                        set remainingCount to remainingCount - 1
                    end repeat
                else
                    repeat with msgIndex from messageCount to 1 by -1
                        if remainingCount is less than or equal to 0 then
                            exit repeat
                        end if
                        set messageRef to item msgIndex of mailboxMessages
                        set rowText to (id of messageRef as text) & tab & my sanitize(message id of messageRef) & tab & my sanitize(subject of messageRef) & tab & my sanitize(sender of messageRef) & tab & my sanitize(date received of messageRef as text) & tab & accountLabel & tab & mailboxLabel
                        set outText to my emitRow(outText, rowText)
                        set remainingCount to remainingCount - 1
                    end repeat
                end if
            end repeat
        end repeat
    end tell
    return outText
end run
"""
    )
    output = run_osascript(script, [account, mailbox, str(limit), order])
    return parse_tsv(
        output,
        ["id", "message_id", "subject", "sender", "date_received", "account", "mailbox"],
    )


def view_message(account: str, mailbox: str, target_id: str, target_message_id: str) -> dict[str, str]:
    script = (
        script_helpers()
        + """
on run argv
    set accountName to item 1 of argv
    set mailboxName to item 2 of argv
    set targetId to item 3 of argv
    set targetMessageId to item 4 of argv

    tell application "Mail"
        if accountName is "" then
            set targetAccounts to every account
        else
            set targetAccounts to {account accountName}
        end if

        repeat with accountRef in targetAccounts
            if mailboxName is "" then
                set targetMailboxes to every mailbox of accountRef
            else
                set targetMailboxes to {my mailboxByPath(accountRef, mailboxName)}
            end if

            repeat with mailboxRef in targetMailboxes
                if targetId is not "" then
                    try
                        set matches to (messages of mailboxRef whose id is (targetId as integer))
                    on error
                        set matches to {}
                    end try
                else
                    set matches to (messages of mailboxRef whose message id is targetMessageId)
                end if

                if (count of matches) > 0 then
                    set messageRef to item 1 of matches
                    set headerRow to (id of messageRef as text) & tab & my sanitize(message id of messageRef) & tab & my sanitize(subject of messageRef) & tab & my sanitize(sender of messageRef) & tab & my sanitize(date received of messageRef as text) & tab & (name of accountRef) & tab & my mailboxPath(mailboxRef)
                    return headerRow & linefeed & (content of messageRef)
                end if
            end repeat
        end repeat
    end tell

    if targetId is not "" then
        error "No message found with id " & targetId
    else
        error "No message found with message-id " & targetMessageId
    end if
end run
"""
    )
    output = run_osascript(script, [account, mailbox, target_id, target_message_id])
    if not output:
        raise AppleMailError("Unexpected empty output while viewing message")
    header_line, _, body = output.partition("\n")
    rows = parse_tsv(
        header_line,
        ["id", "message_id", "subject", "sender", "date", "account", "mailbox"],
    )
    if not rows:
        raise AppleMailError("Unexpected output while viewing message")
    message = rows[0]
    message["content"] = body
    return message


def show_message(account: str, mailbox: str, target_id: str, target_message_id: str) -> None:
    script = (
        script_helpers()
        + """
on run argv
    set accountName to item 1 of argv
    set mailboxName to item 2 of argv
    set targetId to item 3 of argv
    set targetMessageId to item 4 of argv

    tell application "Mail"
        activate
        if accountName is "" then
            set targetAccounts to every account
        else
            set targetAccounts to {account accountName}
        end if

        repeat with accountRef in targetAccounts
            if mailboxName is "" then
                set targetMailboxes to every mailbox of accountRef
            else
                set targetMailboxes to {my mailboxByPath(accountRef, mailboxName)}
            end if

            repeat with mailboxRef in targetMailboxes
                if targetId is not "" then
                    try
                        set matches to (messages of mailboxRef whose id is (targetId as integer))
                    on error
                        set matches to {}
                    end try
                else
                    set matches to (messages of mailboxRef whose message id is targetMessageId)
                end if

                if (count of matches) > 0 then
                    set theMessage to item 1 of matches
                    
                    if (count of message viewers) is 0 then
                        make new message viewer
                    end if
                    
                    set selected messages of message viewer 1 to {theMessage}
                    return
                end if
            end repeat
        end repeat
        
        if targetId is not "" then
            error "No message found with id " & targetId
        else
            error "No message found with message-id " & targetMessageId
        end if
    end tell
end run
"""
    )
    run_osascript(script, [account, mailbox, target_id, target_message_id])


def send_message(
    to_addresses: str,
    cc_addresses: str,
    bcc_addresses: str,
    subject: str,
    body: str,
    account: str,
) -> None:
    script = (
        script_helpers()
        + """
on run argv
    set toCsv to item 1 of argv
    set ccCsv to item 2 of argv
    set bccCsv to item 3 of argv
    set subjectText to item 4 of argv
    set bodyText to item 5 of argv
    set accountName to item 6 of argv

    tell application "Mail"
        set outgoingRef to make new outgoing message with properties {subject:subjectText, content:bodyText & return & return, visible:false}
        tell outgoingRef
            repeat with addr in my splitByDelimiter(toCsv, ",")
                set cleanAddr to my trimValue(contents of addr)
                if cleanAddr is not "" then
                    make new to recipient at end of to recipients with properties {address:cleanAddr}
                end if
            end repeat
            repeat with addr in my splitByDelimiter(ccCsv, ",")
                set cleanAddr to my trimValue(contents of addr)
                if cleanAddr is not "" then
                    make new cc recipient at end of cc recipients with properties {address:cleanAddr}
                end if
            end repeat
            repeat with addr in my splitByDelimiter(bccCsv, ",")
                set cleanAddr to my trimValue(contents of addr)
                if cleanAddr is not "" then
                    make new bcc recipient at end of bcc recipients with properties {address:cleanAddr}
                end if
            end repeat
            if accountName is not "" then
                set accountEmails to email addresses of account accountName
                if (count of accountEmails) > 0 then
                    set sender of outgoingRef to item 1 of accountEmails
                end if
            end if
            send
        end tell
    end tell
end run
"""
    )
    run_osascript(script, [to_addresses, cc_addresses, bcc_addresses, subject, body, account])


def create_mailbox(account: str, mailbox_name: str, parent_mailbox: str) -> None:
    script = (
        script_helpers()
        + """
on run argv
    set accountName to item 1 of argv
    set mailboxName to item 2 of argv
    set parentMailboxName to item 3 of argv
    tell application "Mail"
        set accountRef to account accountName
        if parentMailboxName is "" then
            make new mailbox at accountRef with properties {name:mailboxName}
        else
            set parentRef to my mailboxByPath(accountRef, parentMailboxName)
            make new mailbox at parentRef with properties {name:mailboxName}
        end if
    end tell
end run
"""
    )
    run_osascript(script, [account, mailbox_name, parent_mailbox])


def rename_mailbox(account: str, mailbox_name: str, new_name: str) -> None:
    script = (
        script_helpers()
        + """
on run argv
    set accountName to item 1 of argv
    set mailboxName to item 2 of argv
    set newName to item 3 of argv
    tell application "Mail"
        set accountRef to account accountName
        set mailboxRef to my mailboxByPath(accountRef, mailboxName)
        set name of mailboxRef to newName
    end tell
end run
"""
    )
    run_osascript(script, [account, mailbox_name, new_name])


def delete_mailbox(account: str, mailbox_name: str) -> None:
    script = (
        script_helpers()
        + """
on run argv
    set accountName to item 1 of argv
    set mailboxName to item 2 of argv
    tell application "Mail"
        set accountRef to account accountName
        set mailboxRef to my mailboxByPath(accountRef, mailboxName)
        delete mailboxRef
    end tell
end run
"""
    )
    run_osascript(script, [account, mailbox_name])


def move_message(
    account: str,
    source_mailbox: str,
    destination_mailbox: str,
    target_id: str,
    target_message_id: str,
) -> None:
    script = (
        script_helpers()
        + """
on run argv
    set accountName to item 1 of argv
    set sourceMailboxName to item 2 of argv
    set destinationMailboxName to item 3 of argv
    set targetId to item 4 of argv
    set targetMessageId to item 5 of argv

    tell application "Mail"
        if accountName is "" then
            set targetAccounts to every account
        else
            set targetAccounts to {account accountName}
        end if

        repeat with accountRef in targetAccounts
            if sourceMailboxName is "" then
                set sourceMailboxes to every mailbox of accountRef
            else
                set sourceMailboxes to {my mailboxByPath(accountRef, sourceMailboxName)}
            end if

            repeat with mailboxRef in sourceMailboxes
                if targetId is not "" then
                    try
                        set matches to (messages of mailboxRef whose id is (targetId as integer))
                    on error
                        set matches to {}
                    end try
                else
                    set matches to (messages of mailboxRef whose message id is targetMessageId)
                end if

                if (count of matches) > 0 then
                    set destinationRef to my mailboxByPath(accountRef, destinationMailboxName)
                    move (item 1 of matches) to destinationRef
                    return
                end if
            end repeat
        end repeat
    end tell

    if targetId is not "" then
        error "No message found with id " & targetId
    else
        error "No message found with message-id " & targetMessageId
    end if
end run
"""
    )
    run_osascript(script, [account, source_mailbox, destination_mailbox, target_id, target_message_id])


def triage_message(account: str, mailbox: str, target_id: str, target_message_id: str, action: str) -> None:
    script = (
        script_helpers()
        + """
on run argv
    set accountName to item 1 of argv
    set mailboxName to item 2 of argv
    set targetId to item 3 of argv
    set targetMessageId to item 4 of argv
    set actionName to item 5 of argv

    tell application "Mail"
        if accountName is "" then
            set targetAccounts to every account
        else
            set targetAccounts to {account accountName}
        end if

        repeat with accountRef in targetAccounts
            if mailboxName is "" then
                set sourceMailboxes to every mailbox of accountRef
            else
                set sourceMailboxes to {my mailboxByPath(accountRef, mailboxName)}
            end if

            repeat with mailboxRef in sourceMailboxes
                if targetId is not "" then
                    try
                        set matches to (messages of mailboxRef whose id is (targetId as integer))
                    on error
                        set matches to {}
                    end try
                else
                    set matches to (messages of mailboxRef whose message id is targetMessageId)
                end if

                if (count of matches) > 0 then
                    set messageRef to item 1 of matches
                    if actionName is "trash" then
                        delete messageRef
                        return
                    else if actionName is "archive" then
                        set archiveRef to my mailboxByPath(accountRef, "Archive")
                        move messageRef to archiveRef
                        return
                    else if actionName is "spam" then
                        set junkRef to my mailboxByPath(accountRef, "Junk")
                        move messageRef to junkRef
                        return
                    else
                        error "Unsupported action: " & actionName
                    end if
                end if
            end repeat
        end repeat
    end tell

    if targetId is not "" then
        error "No message found with id " & targetId
    else
        error "No message found with message-id " & targetMessageId
    end if
end run
"""
    )
    run_osascript(script, [account, mailbox, target_id, target_message_id, action])


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mail-app",
        description="Apple Mail command-line interface powered by AppleScript.",
        formatter_class=SubcommandHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    root_subparsers = parser.add_subparsers(dest="resource", required=True, title="commands", metavar="COMMAND")

    messages_parser = root_subparsers.add_parser(
        "messages",
        aliases=["msgs", "msg"],
        help="Message operations",
        description="List, inspect, send, move, and triage messages.",
        formatter_class=SubcommandHelpFormatter,
    )
    messages_subparsers = messages_parser.add_subparsers(dest="message_command", required=True, title="commands", metavar="COMMAND")

    messages_list_parser = messages_subparsers.add_parser(
        "list",
        aliases=["ls"],
        help="List messages",
        description="List messages with optional account/mailbox filters and sort order.",
    )
    messages_list_parser.add_argument("--account", default="", help="Mail account name")
    messages_list_parser.add_argument("--mailbox", default="", help="Mailbox path (requires --account)")
    messages_list_parser.add_argument("--limit", type=int, default=DEFAULT_LIST_LIMIT, help="Maximum results")
    messages_list_parser.add_argument("--order", choices=("desc", "asc"), default="desc", help="Sort order by received date")
    messages_list_parser.add_argument("--json", action="store_true", help="JSON output")
    messages_list_parser.set_defaults(func=cmd_messages_list, parser_obj=messages_list_parser)

    messages_view_parser = messages_subparsers.add_parser(
        "view",
        aliases=["v"],
        help="View a message",
        description="Show message metadata and content, or output body only.",
    )
    add_message_selector_arguments(messages_view_parser)
    messages_view_parser.add_argument("--account", default="", help="Mail account name")
    messages_view_parser.add_argument("--mailbox", default="", help="Mailbox path (requires --account)")
    messages_view_parser.add_argument("--body-only", action="store_true", help="Only output message body")
    messages_view_parser.add_argument("--json", action="store_true", help="JSON output")
    messages_view_parser.set_defaults(func=cmd_messages_view, parser_obj=messages_view_parser)

    messages_show_parser = messages_subparsers.add_parser(
        "show",
        aliases=["open"],
        help="Show a message in the Mail app",
        description="Reveal one message by id or message-id in the macOS Mail application.",
    )
    add_message_selector_arguments(messages_show_parser)
    messages_show_parser.add_argument("--account", default="", help="Mail account name")
    messages_show_parser.add_argument("--mailbox", default="", help="Mailbox path (requires --account)")
    messages_show_parser.set_defaults(func=cmd_messages_show, parser_obj=messages_show_parser)

    messages_send_parser = messages_subparsers.add_parser(
        "send",
        aliases=["s"],
        help="Create and send a message",
        description="Create and send a new outgoing message.",
    )
    messages_send_parser.add_argument("--to", required=True, help="Comma-separated recipient addresses")
    messages_send_parser.add_argument("--cc", default="", help="Comma-separated CC addresses")
    messages_send_parser.add_argument("--bcc", default="", help="Comma-separated BCC addresses")
    messages_send_parser.add_argument("--subject", required=True, help="Subject line")
    messages_send_parser.add_argument("--body", required=True, help="Message body")
    messages_send_parser.add_argument("--account", default="", help="Mail account name to send from")
    messages_send_parser.set_defaults(func=cmd_messages_send)

    messages_move_parser = messages_subparsers.add_parser(
        "move",
        aliases=["mv"],
        help="Move a message",
        description="Move a message to another mailbox.",
    )
    add_message_selector_arguments(messages_move_parser)
    messages_move_parser.add_argument("--destination-mailbox", required=True, help="Destination mailbox path")
    messages_move_parser.add_argument("--account", default="", help="Mail account name")
    messages_move_parser.add_argument("--source-mailbox", default="", help="Source mailbox path (requires --account)")
    messages_move_parser.set_defaults(func=cmd_messages_move, parser_obj=messages_move_parser)

    for action_name in ("archive", "trash", "spam"):
        action_parser = messages_subparsers.add_parser(
            action_name,
            aliases=ACTION_ALIASES[action_name],
            help=f"{action_name.title()} a message",
            description=f"{action_name.title()} a message selected by id or message-id.",
        )
        add_message_selector_arguments(action_parser)
        action_parser.add_argument("--account", default="", help="Mail account name")
        action_parser.add_argument("--mailbox", default="", help="Mailbox path (requires --account)")
        action_parser.set_defaults(func=cmd_messages_action, action_name=action_name, parser_obj=action_parser)

    mailboxes_parser = root_subparsers.add_parser(
        "mailboxes",
        aliases=["mbox", "mboxs", "mboxes"],
        help="Mailbox operations",
        description="List and manage mailboxes.",
        formatter_class=SubcommandHelpFormatter,
    )
    mailboxes_subparsers = mailboxes_parser.add_subparsers(dest="mailbox_command", required=True, title="commands", metavar="COMMAND")

    mailboxes_list_parser = mailboxes_subparsers.add_parser(
        "list",
        aliases=["ls"],
        help="List mailboxes",
        description="List available mailboxes, optionally scoped to an account.",
    )
    mailboxes_list_parser.add_argument("--account", default="", help="Mail account name")
    mailboxes_list_parser.add_argument("--json", action="store_true", help="JSON output")
    mailboxes_list_parser.set_defaults(func=cmd_mailboxes_list)

    mailboxes_create_parser = mailboxes_subparsers.add_parser(
        "create",
        help="Create a mailbox",
        description="Create a mailbox, optionally under a parent mailbox.",
    )
    mailboxes_create_parser.add_argument("--account", required=True, help="Mail account name")
    mailboxes_create_parser.add_argument("--name", required=True, help="Mailbox name")
    mailboxes_create_parser.add_argument("--parent-mailbox", default="", help="Parent mailbox path")
    mailboxes_create_parser.set_defaults(func=cmd_mailboxes_create)

    mailboxes_rename_parser = mailboxes_subparsers.add_parser(
        "rename",
        aliases=["mv"],
        help="Rename a mailbox",
        description="Rename an existing mailbox.",
    )
    mailboxes_rename_parser.add_argument("--account", required=True, help="Mail account name")
    mailboxes_rename_parser.add_argument("--mailbox", required=True, help="Mailbox path")
    mailboxes_rename_parser.add_argument("--new-name", required=True, help="New mailbox name")
    mailboxes_rename_parser.set_defaults(func=cmd_mailboxes_rename)

    mailboxes_delete_parser = mailboxes_subparsers.add_parser(
        "delete",
        aliases=["remove", "rm"],
        help="Delete a mailbox",
        description="Delete a mailbox.",
    )
    mailboxes_delete_parser.add_argument("--account", required=True, help="Mail account name")
    mailboxes_delete_parser.add_argument("--mailbox", required=True, help="Mailbox path")
    mailboxes_delete_parser.set_defaults(func=cmd_mailboxes_delete)

    return parser


def cmd_messages_list(args: argparse.Namespace) -> None:
    require_account_if_mailbox(args.account, args.mailbox, args.parser_obj)
    if args.limit <= 0:
        args.parser_obj.error("--limit must be greater than 0")
    rows = list_messages(args.account, args.mailbox, args.limit, args.order)
    
    formatted_rows = []
    for row in rows:
        formatted_row = {
            "id": row.get("id", ""),
            "subject": row.get("subject", ""),
            "sender": row.get("sender", ""),
            "date": row.get("date_received", ""),
            "account": row.get("account", ""),
            "mailbox": row.get("mailbox", ""),
        }
        formatted_rows.append(formatted_row)
    
    print_rows(formatted_rows, args.json, columns=["id", "subject", "sender", "date", "account", "mailbox"])


def cmd_messages_view(args: argparse.Namespace) -> None:
    require_account_if_mailbox(args.account, args.mailbox, args.parser_obj)
    row = view_message(args.account, args.mailbox, args.id or "", args.message_id or "")
    if args.body_only:
        print(row["content"])
        return
    if args.json:
        print(json.dumps(row, ensure_ascii=False, indent=2))
        return
    
    for k in MESSAGE_DISPLAY_LABELS.keys():
        v = row.get(k, "")
        if v and v != MISSING_VALUE:
            label = MESSAGE_DISPLAY_LABELS.get(k, k)
            print(f"{label}: {v}")
    
    if row.get("content"):
        print("")
        print(row["content"])


def cmd_messages_show(args: argparse.Namespace) -> None:
    require_account_if_mailbox(args.account, args.mailbox, args.parser_obj)
    show_message(args.account, args.mailbox, args.id or "", args.message_id or "")
    print("Message shown in Mail app.")


def cmd_messages_send(args: argparse.Namespace) -> None:
    send_message(args.to, args.cc, args.bcc, args.subject, args.body, args.account)
    print("Message sent.")


def cmd_messages_move(args: argparse.Namespace) -> None:
    require_account_if_mailbox(args.account, args.source_mailbox, args.parser_obj)
    move_message(args.account, args.source_mailbox, args.destination_mailbox, args.id or "", args.message_id or "")
    print("Message moved.")


def cmd_messages_action(args: argparse.Namespace) -> None:
    require_account_if_mailbox(args.account, args.mailbox, args.parser_obj)
    triage_message(args.account, args.mailbox, args.id or "", args.message_id or "", args.action_name)
    verb = {"archive": "archived", "trash": "trashed", "spam": "marked as spam"}[args.action_name]
    print(f"Message {verb}.")


def cmd_mailboxes_list(args: argparse.Namespace) -> None:
    rows = list_mailboxes(args.account)
    print_rows(rows, args.json, print_headers=False)


def cmd_mailboxes_create(args: argparse.Namespace) -> None:
    create_mailbox(args.account, args.name, args.parent_mailbox)
    print("Mailbox created.")


def cmd_mailboxes_rename(args: argparse.Namespace) -> None:
    rename_mailbox(args.account, args.mailbox, args.new_name)
    print("Mailbox renamed.")


def cmd_mailboxes_delete(args: argparse.Namespace) -> None:
    delete_mailbox(args.account, args.mailbox)
    print("Mailbox deleted.")


def main(argv: Sequence[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except AppleMailError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except subprocess.SubprocessError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
