import io
import subprocess
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

import reminders_app
import version


class RemindersAppTests(unittest.TestCase):
    def test_run_osascript_success(self) -> None:
        completed = SimpleNamespace(returncode=0, stdout="ok\n", stderr="")
        with patch("reminders_app.subprocess.run", return_value=completed) as run_mock:
            output = reminders_app.run_osascript("script", ["arg1"])
        self.assertEqual("ok", output)
        self.assertEqual(["osascript", "-s", "h", "-", "arg1"], run_mock.call_args.args[0])

    def test_run_osascript_error(self) -> None:
        completed = SimpleNamespace(returncode=1, stdout="", stderr="script failed")
        with patch("reminders_app.subprocess.run", return_value=completed):
            with self.assertRaises(reminders_app.RemindersAppError):
                reminders_app.run_osascript("script", [])

    def test_run_osascript_timeout(self) -> None:
        with patch(
            "reminders_app.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=30),
        ):
            with self.assertRaises(reminders_app.RemindersAppError):
                reminders_app.run_osascript("script", [])

    def test_reminders_list_defaults(self) -> None:
        with patch("reminders_app.list_reminders", return_value=[]) as list_mock:
            exit_code = reminders_app.main(["reminders", "list"])
        self.assertEqual(0, exit_code)
        self.assertEqual("", list_mock.call_args.kwargs["list_name"])
        self.assertEqual("uncompleted", list_mock.call_args.kwargs["completed_filter"])
        self.assertEqual(reminders_app.DEFAULT_LIST_LIMIT, list_mock.call_args.kwargs["limit"])
        self.assertEqual("desc", list_mock.call_args.kwargs["order"])

    def test_reminders_list_completed_filter(self) -> None:
        with patch("reminders_app.list_reminders", return_value=[]) as list_mock:
            exit_code = reminders_app.main(["reminders", "list", "--completed"])
        self.assertEqual(0, exit_code)
        self.assertEqual("completed", list_mock.call_args.kwargs["completed_filter"])

    def test_reminders_list_all_filter_and_order(self) -> None:
        with patch("reminders_app.list_reminders", return_value=[]) as list_mock:
            exit_code = reminders_app.main(["reminders", "list", "--all", "--order", "asc", "--limit", "5"])
        self.assertEqual(0, exit_code)
        self.assertEqual("all", list_mock.call_args.kwargs["completed_filter"])
        self.assertEqual(5, list_mock.call_args.kwargs["limit"])
        self.assertEqual("asc", list_mock.call_args.kwargs["order"])

    def test_list_reminders_uses_property_array_loop(self) -> None:
        with patch("reminders_app.run_osascript", return_value="") as script_mock:
            reminders_app.list_reminders(
                list_name="",
                completed_filter="uncompleted",
                due_before="",
                due_after="",
                priority="",
                tag="",
                limit=10,
                order="desc",
            )
        script = script_mock.call_args[0][0]
        self.assertIn("set reminderNames to name of refReminders", script)
        self.assertIn("set reminderCompletion to completed of refReminders", script)
        self.assertIn("set titleText to my sanitize(item i of reminderNames)", script)
        self.assertNotIn("name of reminderRef", script)

    def test_reminders_aliases_work(self) -> None:
        with patch("reminders_app.run_osascript", return_value=""):
            exit_code = reminders_app.main(["rem", "ls"])
        self.assertEqual(0, exit_code)

    def test_lists_aliases_work(self) -> None:
        with patch("reminders_app.run_osascript", return_value=""):
            exit_code = reminders_app.main(["lsts", "ls"])
        self.assertEqual(0, exit_code)

    def test_view_body_only(self) -> None:
        buffer = io.StringIO()
        with patch(
            "reminders_app.run_osascript",
            return_value="1\tTitle\tBody text\tfalse\t\t\t0\tInbox\t",
        ), redirect_stdout(buffer):
            exit_code = reminders_app.main(["reminders", "view", "--id", "1", "--body-only"])
        self.assertEqual(0, exit_code)
        self.assertEqual("Body text", buffer.getvalue().strip())

    def test_update_requires_one_field(self) -> None:
        with self.assertRaises(SystemExit):
            reminders_app.main(["reminders", "update", "--id", "1"])

    def test_bulk_action_requires_selector_or_all(self) -> None:
        with self.assertRaises(SystemExit):
            reminders_app.main(["reminders", "complete"])

    def test_bulk_complete_by_filter(self) -> None:
        with patch(
            "reminders_app.list_reminders",
            return_value=[{"id": "1"}, {"id": "2"}],
        ), patch("reminders_app.set_completed") as set_completed_mock:
            exit_code = reminders_app.main(["reminders", "complete", "--list", "Inbox"])
        self.assertEqual(0, exit_code)
        self.assertEqual(2, set_completed_mock.call_count)

    def test_version_flag_prints_version(self) -> None:
        parser = reminders_app.make_parser()
        buffer = io.StringIO()
        with redirect_stdout(buffer), self.assertRaises(SystemExit):
            parser.parse_args(["--version"])
        self.assertEqual(f"reminders-app {version.__version__}", buffer.getvalue().strip())

    def test_show_reminder(self) -> None:
        with patch("reminders_app.run_osascript") as script_mock:
            exit_code = reminders_app.main(["reminders", "show", "--id", "123"])
        self.assertEqual(0, exit_code)
        script_mock.assert_called_once()
        self.assertIn("show reminderRef", script_mock.call_args[0][0])
        self.assertIn("activate", script_mock.call_args[0][0])

    def test_subprocess_failure_returns_nonzero(self) -> None:
        with patch("reminders_app.run_osascript", side_effect=subprocess.SubprocessError("spawn failed")):
            code = reminders_app.main(["reminders", "list"])
        self.assertEqual(1, code)


if __name__ == "__main__":
    unittest.main()
