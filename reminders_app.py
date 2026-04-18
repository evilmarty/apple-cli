from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any, Sequence

from version import __version__


DEFAULT_LIST_LIMIT = 100
OSASCRIPT_TIMEOUT_SECONDS = 120


class RemindersAppError(RuntimeError):
    pass


def run_osascript(script: str, args: Sequence[str]) -> str:
    try:
        result = subprocess.run(
            ["osascript", "-s", "h", "-", *args],
            input=script,
            text=True,
            capture_output=True,
            check=False,
            timeout=OSASCRIPT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RemindersAppError(
            "AppleScript request timed out. Check Reminders automation permissions and retry "
            "with narrower scope (for example --list)."
        ) from exc
    if result.returncode != 0:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        detail = stderr or stdout or f"osascript exited with code {result.returncode}"
        raise RemindersAppError(detail)
    return result.stdout.rstrip("\n")


def parse_tsv(output: str, field_names: Sequence[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if not output.strip():
        return rows
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) != len(field_names):
            raise RemindersAppError("Unexpected AppleScript output format")
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
    
    headers = columns if columns else list(rows[0].keys())
    if print_headers:
        print("\t".join(headers))
    for row in rows:
        # Use .get with key mapping if necessary, or assume rows contain exact keys
        print("\t".join(str(row.get(header, "")) for header in headers))


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

on emitRow(existingOutput, rowText)
    if existingOutput is "" then
        return rowText
    end if
    return existingOutput & linefeed & rowText
end emitRow
"""


def list_lists() -> list[dict[str, str]]:
    script = (
        script_helpers()
        + """
on run argv
    set outText to ""
    tell application "Reminders"
        repeat with listRef in every list
            set outText to my emitRow(outText, (id of listRef as text) & tab & my sanitize(name of listRef))
        end repeat
    end tell
    return outText
end run
"""
    )
    output = run_osascript(script, [])
    return parse_tsv(output, ["id", "name"])


def list_reminders(
    list_name: str,
    completed_filter: str,
    due_before: str,
    due_after: str,
    priority: str,
    tag: str,
    limit: int | None,
    order: str,
) -> list[dict[str, str]]:
    max_count = "" if limit is None else str(limit)
    script = (
        script_helpers()
        + """
on run argv
    set listName to item 1 of argv
    set completedFilter to item 2 of argv
    set dueBeforeText to item 3 of argv
    set dueAfterText to item 4 of argv
    set priorityFilter to item 5 of argv
    set tagFilter to item 6 of argv
    set maxCountText to item 7 of argv
    set sortOrder to item 8 of argv

    set outText to ""
    set remainingCount to -1
    if maxCountText is not "" then
        set remainingCount to maxCountText as integer
    end if

    set dueBeforeDate to missing value
    if dueBeforeText is not "" then
        set dueBeforeDate to date dueBeforeText
    end if

    set dueAfterDate to missing value
    if dueAfterText is not "" then
        set dueAfterDate to date dueAfterText
    end if

    tell application "Reminders"
        if listName is "" then
            try
                set targetLists to {default list}
            on error
                set targetLists to {first list}
            end try
        else
            set targetLists to {list listName}
        end if

        repeat with aList in targetLists
            if remainingCount is 0 then
                exit repeat
            end if
            tell aList
                if completedFilter is "completed" then
                    set refReminders to a reference to (every reminder whose completed is true)
                else if completedFilter is "uncompleted" then
                    set refReminders to a reference to (every reminder whose completed is false)
                else
                    set refReminders to a reference to every reminder
                end if

                set reminderCount to count of refReminders
                if reminderCount is 0 then
                    if remainingCount is 0 then
                        exit repeat
                    end if
                else
                    set reminderIds to id of refReminders
                    set reminderNames to name of refReminders
                    set reminderBodies to body of refReminders
                    set reminderCompletion to completed of refReminders
                    set reminderDueDates to due date of refReminders
                    set reminderCompletionDates to completion date of refReminders
                    set reminderPriorities to priority of refReminders
                    set listLabel to my sanitize(name)

                    if sortOrder is "asc" then
                        set startIndex to 1
                        set endIndex to reminderCount
                        set stepValue to 1
                    else
                        set startIndex to reminderCount
                        set endIndex to 1
                        set stepValue to -1
                    end if

                    repeat with i from startIndex to endIndex by stepValue
                        if remainingCount is 0 then
                            exit repeat
                        end if

                        set includeReminder to true
                        set titleText to my sanitize(item i of reminderNames)
                        set notesText to my sanitize(item i of reminderBodies)
                        set isCompleted to item i of reminderCompletion
                        set dueDateValue to item i of reminderDueDates
                        set completionDateValue to item i of reminderCompletionDates
                        set priorityText to item i of reminderPriorities as text

                        if dueBeforeDate is not missing value then
                            if dueDateValue is missing value or dueDateValue > dueBeforeDate then
                                set includeReminder to false
                            end if
                        end if

                        if dueAfterDate is not missing value then
                            if dueDateValue is missing value or dueDateValue < dueAfterDate then
                                set includeReminder to false
                            end if
                        end if

                        if priorityFilter is not "" then
                            if priorityText is not priorityFilter then
                                set includeReminder to false
                            end if
                        end if

                        if tagFilter is not "" then
                            if titleText does not contain tagFilter and notesText does not contain tagFilter then
                                set includeReminder to false
                            end if
                        end if

                        if includeReminder then
                            set rowText to (item i of reminderIds as text) & tab & titleText & tab & notesText & tab & (isCompleted as text) & tab & my sanitize(dueDateValue as text) & tab & my sanitize(completionDateValue as text) & tab & priorityText & tab & listLabel & tab
                            set outText to my emitRow(outText, rowText)
                            if remainingCount > 0 then
                                set remainingCount to remainingCount - 1
                            end if
                        end if
                    end repeat
                end if
            end tell
        end repeat
    end tell

    return outText
end run
"""
    )
    output = run_osascript(
        script,
        [list_name, completed_filter, due_before, due_after, priority, tag, max_count, order],
    )
    return parse_tsv(
        output,
        ["id", "title", "notes", "completed", "due_date", "completion_date", "priority", "list", "tags"],
    )


def list_reminders_checklist(list_name: str, completion_mode_code: int, limit: int, order: str) -> str:
    script = (
        script_helpers()
        + """
on run argv
    set listName to item 1 of argv
    set completionModeCode to item 2 of argv as integer
    set maxCount to item 3 of argv as integer
    set sortOrder to item 4 of argv

    set outText to ""
    set emittedCount to 0

    tell application "Reminders"
        if listName is "" then
            try
                set allLists to {default list}
            on error
                set allLists to {first list}
            end try
        else
            set allLists to {list listName}
        end if

        repeat with aList in allLists
            tell aList
                set listLabel to my sanitize(name)
                if completionModeCode is 0 then
                    set reminderNames to name of (every reminder whose completed is false)
                    set reminderCompletion to completed of (every reminder whose completed is false)
                else if completionModeCode is 1 then
                    set reminderNames to name of (every reminder whose completed is true)
                    set reminderCompletion to completed of (every reminder whose completed is true)
                else
                    set reminderNames to name of every reminder
                    set reminderCompletion to completed of every reminder
                end if

                if (count of reminderNames) > 0 then
                    set sectionText to ""
                    if sortOrder is "asc" then
                        set startIndex to 1
                        set endIndex to (count of reminderNames)
                        set stepValue to 1
                    else
                        set startIndex to (count of reminderNames)
                        set endIndex to 1
                        set stepValue to -1
                    end if

                    repeat with i from startIndex to endIndex by stepValue
                        if emittedCount is greater than or equal to maxCount then
                            exit repeat
                        end if
                        set rName to my sanitize(item i of reminderNames)
                        set rDone to item i of reminderCompletion

                        if rDone then
                            set sectionText to sectionText & "[X] " & rName & linefeed
                        else
                            set sectionText to sectionText & "[ ] " & rName & linefeed
                        end if
                        set emittedCount to emittedCount + 1
                    end repeat

                    if sectionText is not "" then
                        set outText to outText & "--- " & listLabel & " ---" & linefeed & sectionText & linefeed
                    end if
                end if

                if emittedCount is greater than or equal to maxCount then
                    exit repeat
                end if
            end tell
        end repeat
    end tell
    return outText
end run
"""
    )
    return run_osascript(script, [list_name, str(completion_mode_code), str(limit), order])


def resolve_list_completion_mode(args: argparse.Namespace) -> int:
    if args.list_all:
        return 2
    if args.list_completed:
        return 1
    return 0


def normalize_reminder_id(reminder_id: str) -> str:
    prefix = "x-apple-reminder://"
    if reminder_id and not reminder_id.startswith(prefix):
        return prefix + reminder_id
    return reminder_id


def view_reminder(reminder_id: str) -> dict[str, str]:
    reminder_id = normalize_reminder_id(reminder_id)
    script = (
        script_helpers()
        + """
on run argv
    set targetId to item 1 of argv
    tell application "Reminders"
        try
            set reminderRef to reminder id targetId
            set listRef to container of reminderRef
            set r_id to id of reminderRef as text
            set r_name to name of reminderRef
            set r_body to body of reminderRef
            set r_comp to completed of reminderRef as text
            set r_due to due date of reminderRef as text
            set r_cdate to completion date of reminderRef as text
            set r_prio to priority of reminderRef as text
            set l_name to name of listRef
            set tagText to ""
            
            return r_id & tab & my sanitize(r_name) & tab & my sanitize(r_body) & tab & r_comp & tab & my sanitize(r_due) & tab & my sanitize(r_cdate) & tab & r_prio & tab & my sanitize(l_name) & tab & tagText
        on error
            error "No reminder found with id " & targetId
        end try
    end tell
end run
"""
    )
    output = run_osascript(script, [reminder_id])
    rows = parse_tsv(
        output,
        ["id", "title", "notes", "completed", "due_date", "completion_date", "priority", "list", "tags"],
    )
    if not rows:
        raise RemindersAppError("Unexpected output while viewing reminder")
    
    row = rows[0]
    prefix = "x-apple-reminder://"
    row["id"] = row["id"].removeprefix(prefix)
    return row


def create_list(name: str) -> None:
    script = """
on run argv
    set listName to item 1 of argv
    tell application "Reminders"
        make new list with properties {name:listName}
    end tell
end run
"""
    run_osascript(script, [name])


def rename_list(list_name: str, new_name: str) -> None:
    script = """
on run argv
    set listName to item 1 of argv
    set newName to item 2 of argv
    tell application "Reminders"
        set name of list listName to newName
    end tell
end run
"""
    run_osascript(script, [list_name, new_name])


def delete_list(list_name: str) -> None:
    script = """
on run argv
    set listName to item 1 of argv
    tell application "Reminders"
        delete list listName
    end tell
end run
"""
    run_osascript(script, [list_name])


def create_reminder(title: str, notes: str, list_name: str, due_date: str, priority: str) -> None:
    script = """
on run argv
    set titleText to item 1 of argv
    set notesText to item 2 of argv
    set listName to item 3 of argv
    set dueDateText to item 4 of argv
    set priorityText to item 5 of argv

    tell application "Reminders"
        if listName is "" then
            set targetList to first list
        else
            set targetList to list listName
        end if

        set reminderRef to make new reminder at end of reminders of targetList with properties {name:titleText, body:notesText}

        if dueDateText is not "" then
            set due date of reminderRef to date dueDateText
        end if
        if priorityText is not "" then
            set priority of reminderRef to priorityText as integer
        end if
    end tell
end run
"""
    run_osascript(script, [title, notes, list_name, due_date, priority])


def update_reminder(
    reminder_id: str,
    title: str,
    notes: str,
    due_date: str,
    priority: str,
    list_name: str,
) -> None:
    reminder_id = normalize_reminder_id(reminder_id)
    script = """
on run argv
    set targetId to item 1 of argv
    set titleText to item 2 of argv
    set notesText to item 3 of argv
    set dueDateText to item 4 of argv
    set priorityText to item 5 of argv
    set targetListName to item 6 of argv

    tell application "Reminders"
        try
            set reminderRef to reminder id targetId
            if titleText is not "" then set name of reminderRef to titleText
            if notesText is not "" then set body of reminderRef to notesText
            if dueDateText is not "" then set due date of reminderRef to date dueDateText
            if priorityText is not "" then set priority of reminderRef to priorityText as integer
            if targetListName is not "" then
                move reminderRef to end of reminders of list targetListName
            end if
        on error
            error "No reminder found with id " & targetId
        end try
    end tell
end run
"""
    run_osascript(script, [reminder_id, title, notes, due_date, priority, list_name])


def set_completed(reminder_id: str, completed: bool) -> None:
    reminder_id = normalize_reminder_id(reminder_id)
    completed_text = "true" if completed else "false"
    script = """
on run argv
    set targetId to item 1 of argv
    set completedText to item 2 of argv
    if completedText is "true" then
        set targetCompleted to true
    else
        set targetCompleted to false
    end if

    tell application "Reminders"
        try
            set reminderRef to reminder id targetId
            set completed of reminderRef to targetCompleted
        on error
            error "No reminder found with id " & targetId
        end try
    end tell
end run
"""
    run_osascript(script, [reminder_id, completed_text])


def delete_reminder(reminder_id: str) -> None:
    reminder_id = normalize_reminder_id(reminder_id)
    script = """
on run argv
    set targetId to item 1 of argv
    tell application "Reminders"
        try
            delete reminder id targetId
        on error
            error "No reminder found with id " & targetId
        end try
    end tell
end run
"""
    run_osascript(script, [reminder_id])


def move_reminder(reminder_id: str, destination_list: str) -> None:
    reminder_id = normalize_reminder_id(reminder_id)
    script = """
on run argv
    set targetId to item 1 of argv
    set destinationListName to item 2 of argv
    tell application "Reminders"
        try
            set reminderRef to reminder id targetId
            move reminderRef to end of reminders of list destinationListName
        on error
            error "No reminder found with id " & targetId
        end try
    end tell
end run
"""
    run_osascript(script, [reminder_id, destination_list])


def add_common_filter_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--list", default="", help="Reminders list name")
    completion_group = parser.add_mutually_exclusive_group()
    completion_group.add_argument("--completed", action="store_true", help="Only completed reminders")
    completion_group.add_argument("--uncompleted", action="store_true", help="Only uncompleted reminders")
    parser.add_argument("--due-before", default="", help="Only reminders due on/before date/time")
    parser.add_argument("--due-after", default="", help="Only reminders due on/after date/time")
    parser.add_argument("--priority", default="", help="Only reminders matching priority (0-9)")
    parser.add_argument("--tag", default="", help="Only reminders containing tag text")


def determine_completed_filter(args: argparse.Namespace) -> str:
    if args.completed:
        return "completed"
    if args.uncompleted:
        return "uncompleted"
    return "all"


def has_query_selector(args: argparse.Namespace) -> bool:
    return bool(args.list or args.completed or args.uncompleted or args.due_before or args.due_after or args.priority or args.tag)


def resolve_target_ids_for_action(args: argparse.Namespace) -> list[str]:
    if args.id:
        return [args.id]
    if not args.all and not has_query_selector(args):
        args.parser_obj.error("Provide --id, at least one filter selector, or --all")
    rows = list_reminders(
        list_name=args.list,
        completed_filter=determine_completed_filter(args),
        due_before=args.due_before,
        due_after=args.due_after,
        priority=args.priority,
        tag=args.tag,
        limit=None,
        order="desc",
    )
    ids = [row["id"] for row in rows]
    prefix = "x-apple-reminder://"
    return [i.removeprefix(prefix) for i in ids]


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reminders-app",
        description="Apple Reminders command-line interface powered by AppleScript.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    root_subparsers = parser.add_subparsers(dest="resource", required=True)

    reminders_parser = root_subparsers.add_parser(
        "reminders",
        aliases=["rem", "rems"],
        help="Reminder operations",
        description="List, view, create, update, complete, delete, and move reminders.",
    )
    reminders_subparsers = reminders_parser.add_subparsers(dest="reminder_command", required=True)

    reminders_list_parser = reminders_subparsers.add_parser(
        "list",
        aliases=["ls"],
        help="List reminders",
        description="List reminders from one list with completion filtering, limit, and order.",
    )
    reminders_list_parser.add_argument("--list", default="", help="Reminders list name (defaults to default list)")
    reminders_list_parser.add_argument("--limit", type=int, default=DEFAULT_LIST_LIMIT, help="Maximum reminders to show")
    reminders_list_parser.add_argument("--order", choices=("desc", "asc"), default="desc", help="Sort order")
    completion_group = reminders_list_parser.add_mutually_exclusive_group()
    completion_group.add_argument("--completed", dest="list_completed", action="store_true", help="Only completed reminders")
    completion_group.add_argument("--all", dest="list_all", action="store_true", help="Include all reminders")
    reminders_list_parser.add_argument("--json", action="store_true", help="JSON output")
    reminders_list_parser.set_defaults(func=cmd_reminders_list, parser_obj=reminders_list_parser)

    reminders_view_parser = reminders_subparsers.add_parser(
        "view",
        aliases=["v"],
        help="View a reminder",
        description="View one reminder by id.",
    )
    reminders_view_parser.add_argument("--id", required=True, help="Reminder id")
    reminders_view_parser.add_argument("--body-only", action="store_true", help="Only output reminder notes")
    reminders_view_parser.add_argument("--json", action="store_true", help="JSON output")
    reminders_view_parser.set_defaults(func=cmd_reminders_view)

    reminders_create_parser = reminders_subparsers.add_parser(
        "create",
        aliases=["add"],
        help="Create a reminder",
        description="Create a new reminder.",
    )
    reminders_create_parser.add_argument("--title", required=True, help="Reminder title")
    reminders_create_parser.add_argument("--notes", default="", help="Reminder notes/body")
    reminders_create_parser.add_argument("--list", default="", help="Destination list")
    reminders_create_parser.add_argument("--due-date", default="", help="Due date/time text")
    reminders_create_parser.add_argument("--priority", default="", help="Priority (0-9)")
    reminders_create_parser.set_defaults(func=cmd_reminders_create)

    reminders_update_parser = reminders_subparsers.add_parser(
        "update",
        aliases=["set"],
        help="Update a reminder",
        description="Update fields of an existing reminder.",
    )
    reminders_update_parser.add_argument("--id", required=True, help="Reminder id")
    reminders_update_parser.add_argument("--title", default="", help="New title")
    reminders_update_parser.add_argument("--notes", default="", help="New notes")
    reminders_update_parser.add_argument("--due-date", default="", help="New due date/time text")
    reminders_update_parser.add_argument("--priority", default="", help="New priority (0-9)")
    reminders_update_parser.add_argument("--list", default="", help="Move reminder to list")
    reminders_update_parser.set_defaults(func=cmd_reminders_update, parser_obj=reminders_update_parser)

    reminders_complete_parser = reminders_subparsers.add_parser(
        "complete",
        aliases=["done"],
        help="Complete reminders",
        description="Mark one or many reminders as completed.",
    )
    reminders_complete_parser.add_argument("--id", default="", help="Reminder id")
    reminders_complete_parser.add_argument("--all", action="store_true", help="Apply to all reminders")
    add_common_filter_arguments(reminders_complete_parser)
    reminders_complete_parser.set_defaults(func=cmd_reminders_complete, parser_obj=reminders_complete_parser)

    reminders_uncomplete_parser = reminders_subparsers.add_parser(
        "uncomplete",
        aliases=["undone"],
        help="Uncomplete reminders",
        description="Mark one or many reminders as not completed.",
    )
    reminders_uncomplete_parser.add_argument("--id", default="", help="Reminder id")
    reminders_uncomplete_parser.add_argument("--all", action="store_true", help="Apply to all reminders")
    add_common_filter_arguments(reminders_uncomplete_parser)
    reminders_uncomplete_parser.set_defaults(func=cmd_reminders_uncomplete, parser_obj=reminders_uncomplete_parser)

    reminders_delete_parser = reminders_subparsers.add_parser(
        "delete",
        aliases=["remove", "rm"],
        help="Delete reminders",
        description="Delete one or many reminders.",
    )
    reminders_delete_parser.add_argument("--id", default="", help="Reminder id")
    reminders_delete_parser.add_argument("--all", action="store_true", help="Apply to all reminders")
    add_common_filter_arguments(reminders_delete_parser)
    reminders_delete_parser.set_defaults(func=cmd_reminders_delete, parser_obj=reminders_delete_parser)

    reminders_move_parser = reminders_subparsers.add_parser(
        "move",
        aliases=["mv"],
        help="Move reminders",
        description="Move one or many reminders to another list.",
    )
    reminders_move_parser.add_argument("--destination-list", required=True, help="Target list")
    reminders_move_parser.add_argument("--id", default="", help="Reminder id")
    reminders_move_parser.add_argument("--all", action="store_true", help="Apply to all reminders")
    add_common_filter_arguments(reminders_move_parser)
    reminders_move_parser.set_defaults(func=cmd_reminders_move, parser_obj=reminders_move_parser)

    lists_parser = root_subparsers.add_parser(
        "lists",
        aliases=["lst", "lsts"],
        help="List operations",
        description="List and manage reminder lists.",
    )
    lists_subparsers = lists_parser.add_subparsers(dest="list_command", required=True)

    lists_list_parser = lists_subparsers.add_parser("list", aliases=["ls"], help="List reminder lists", description="List reminder lists.")
    lists_list_parser.add_argument("--json", action="store_true", help="JSON output")
    lists_list_parser.set_defaults(func=cmd_lists_list)

    lists_create_parser = lists_subparsers.add_parser("create", aliases=["add"], help="Create a list", description="Create a reminder list.")
    lists_create_parser.add_argument("--name", required=True, help="List name")
    lists_create_parser.set_defaults(func=cmd_lists_create)

    lists_rename_parser = lists_subparsers.add_parser("rename", aliases=["mv"], help="Rename a list", description="Rename a reminder list.")
    lists_rename_parser.add_argument("--list", required=True, help="Current list name")
    lists_rename_parser.add_argument("--new-name", required=True, help="New list name")
    lists_rename_parser.set_defaults(func=cmd_lists_rename)

    lists_delete_parser = lists_subparsers.add_parser("delete", aliases=["remove", "rm"], help="Delete a list", description="Delete a reminder list.")
    lists_delete_parser.add_argument("--list", required=True, help="List name")
    lists_delete_parser.set_defaults(func=cmd_lists_delete)

    return parser


def cmd_reminders_list(args: argparse.Namespace) -> None:
    if args.limit <= 0:
        args.parser_obj.error("--limit must be greater than 0")

    if args.list_all:
        completed_filter = "all"
    elif args.list_completed:
        completed_filter = "completed"
    else:
        completed_filter = "uncompleted"

    rows = list_reminders(
        list_name=args.list,
        completed_filter=completed_filter,
        due_before="",
        due_after="",
        priority="",
        tag="",
        limit=args.limit,
        order=args.order,
    )

    priority_map = {
        "1": "high",
        "5": "medium",
        "9": "low",
    }

    formatted_rows = []
    prefix = "x-apple-reminder://"
    for row in rows:
        r_id = row.get("id", "").removeprefix(prefix)
            
        p_val = row.get("priority", "0")
        d_val = row.get("due_date", "")
        if d_val == "missing value":
            d_val = "-"
            
        formatted_row = {
            "id": r_id,
            "title": row.get("title", ""),
            "completed": row.get("completed", ""),
            "priority": priority_map.get(p_val, "-"),
            "due date": d_val,
        }
        formatted_rows.append(formatted_row)

    print_rows(formatted_rows, args.json, columns=["id", "title", "completed", "priority", "due date"])


def cmd_reminders_view(args: argparse.Namespace) -> None:
    row = view_reminder(args.id)
    if args.body_only:
        print(row["notes"])
        return
    if args.json:
        print(json.dumps(row, ensure_ascii=False, indent=2))
        return
    print(f"id: {row['id']}")
    print(f"title: {row['title']}")
    print(f"completed: {row['completed']}")
    print(f"due_date: {row['due_date']}")
    print(f"completion_date: {row['completion_date']}")
    print(f"priority: {row['priority']}")
    print(f"list: {row['list']}")
    print(f"tags: {row['tags']}")
    print("")
    print(row["notes"])


def cmd_reminders_create(args: argparse.Namespace) -> None:
    create_reminder(args.title, args.notes, args.list, args.due_date, args.priority)
    print("Reminder created.")


def cmd_reminders_update(args: argparse.Namespace) -> None:
    if not any([args.title, args.notes, args.due_date, args.priority, args.list]):
        args.parser_obj.error("Provide at least one field to update")
    update_reminder(args.id, args.title, args.notes, args.due_date, args.priority, args.list)
    print("Reminder updated.")


def cmd_reminders_complete(args: argparse.Namespace) -> None:
    target_ids = resolve_target_ids_for_action(args)
    for reminder_id in target_ids:
        set_completed(reminder_id, True)
    print(f"Completed {len(target_ids)} reminder(s).")


def cmd_reminders_uncomplete(args: argparse.Namespace) -> None:
    target_ids = resolve_target_ids_for_action(args)
    for reminder_id in target_ids:
        set_completed(reminder_id, False)
    print(f"Uncompleted {len(target_ids)} reminder(s).")


def cmd_reminders_delete(args: argparse.Namespace) -> None:
    target_ids = resolve_target_ids_for_action(args)
    for reminder_id in target_ids:
        delete_reminder(reminder_id)
    print(f"Deleted {len(target_ids)} reminder(s).")


def cmd_reminders_move(args: argparse.Namespace) -> None:
    target_ids = resolve_target_ids_for_action(args)
    for reminder_id in target_ids:
        move_reminder(reminder_id, args.destination_list)
    print(f"Moved {len(target_ids)} reminder(s).")


def cmd_lists_list(args: argparse.Namespace) -> None:
    print_rows(list_lists(), args.json, print_headers=False)


def cmd_lists_create(args: argparse.Namespace) -> None:
    create_list(args.name)
    print("List created.")


def cmd_lists_rename(args: argparse.Namespace) -> None:
    rename_list(args.list, args.new_name)
    print("List renamed.")


def cmd_lists_delete(args: argparse.Namespace) -> None:
    delete_list(args.list)
    print("List deleted.")


def main(argv: Sequence[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except RemindersAppError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except subprocess.SubprocessError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
