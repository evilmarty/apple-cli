import io
import subprocess
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from apple_cli import mail_app
from apple_cli import version


class AppleMailTests(unittest.TestCase):
    def test_main_no_args_shows_help(self) -> None:
        buffer = io.StringIO()
        with redirect_stderr(buffer):
            exit_code = mail_app.main([])
        self.assertEqual(1, exit_code)
        output = buffer.getvalue()
        self.assertIn("usage:", output)
        self.assertIn("mail-app", output)

    def test_run_osascript_success(self) -> None:
        completed = SimpleNamespace(returncode=0, stdout="ok\n", stderr="")
        with patch("apple_cli.mail_app.subprocess.run", return_value=completed) as run_mock:
            output = mail_app.run_osascript("script", ["arg1"])
        self.assertEqual("ok", output)
        run_mock.assert_called_once()
        self.assertEqual(
            ["osascript", "-s", "h", "-", "arg1"],
            run_mock.call_args.args[0],
        )

    def test_run_osascript_error(self) -> None:
        completed = SimpleNamespace(returncode=1, stdout="", stderr="script failed")
        with patch("apple_cli.mail_app.subprocess.run", return_value=completed):
            with self.assertRaises(mail_app.AppleMailError):
                mail_app.run_osascript("script", [])

    def test_messages_list_default_limit(self) -> None:
        with patch("apple_cli.mail_app.run_osascript", return_value=""):
            exit_code = mail_app.main(["messages", "list"])
        self.assertEqual(0, exit_code)

    def test_messages_list_mailbox_requires_account(self) -> None:
        parser = mail_app.make_parser()
        args = parser.parse_args(["messages", "list", "--mailbox", "Inbox"])
        with self.assertRaises(SystemExit):
            mail_app.cmd_messages_list(args)

    def test_messages_list_invokes_default_limit(self) -> None:
        with patch("apple_cli.mail_app.run_osascript", return_value="") as script_mock:
            mail_app.main(["messages", "list"])
        self.assertEqual(str(mail_app.DEFAULT_LIST_LIMIT), script_mock.call_args[0][1][2])
        self.assertEqual("desc", script_mock.call_args[0][1][3])
        self.assertEqual("", script_mock.call_args[0][1][1])
        self.assertIn('set targetMailboxes to {mailbox "INBOX" of accountRef}', script_mock.call_args[0][0])

    def test_messages_list_accepts_asc_order(self) -> None:
        with patch("apple_cli.mail_app.run_osascript", return_value="") as script_mock:
            mail_app.main(["messages", "list", "--order", "asc"])
        self.assertEqual("asc", script_mock.call_args[0][1][3])

    def test_messages_view_uses_id_flag(self) -> None:
        with patch("apple_cli.mail_app.run_osascript", return_value="1\tmid-1\tSubject\tSender\tDate\tAccount\tMailbox\nBody") as script_mock:
            exit_code = mail_app.main(["messages", "view", "--id", "1"])
        self.assertEqual(0, exit_code)
        self.assertIn("whose id is (targetId as integer)", script_mock.call_args[0][0])
        self.assertEqual("1", script_mock.call_args[0][1][2])
        self.assertEqual("", script_mock.call_args[0][1][3])

    def test_messages_view_uses_message_id_flag(self) -> None:
        with patch("apple_cli.mail_app.run_osascript", return_value="1\tmid-1\tSubject\tSender\tDate\tAccount\tMailbox\nBody") as script_mock:
            exit_code = mail_app.main(["messages", "view", "--message-id", "mid-1"])
        self.assertEqual(0, exit_code)
        self.assertIn("whose message id is targetMessageId", script_mock.call_args[0][0])
        self.assertEqual("", script_mock.call_args[0][1][2])
        self.assertEqual("mid-1", script_mock.call_args[0][1][3])

    def test_messages_view_body_only(self) -> None:
        buffer = io.StringIO()
        with patch("apple_cli.mail_app.run_osascript", return_value="1\tmid-1\tSubject\tSender\tDate\tAccount\tMailbox\nBody line"), redirect_stdout(buffer):
            exit_code = mail_app.main(["messages", "view", "--id", "1", "--body-only"])
        self.assertEqual(0, exit_code)
        self.assertEqual("Body line", buffer.getvalue().strip())

    def test_messages_view_json_uses_date_field(self) -> None:
        buffer = io.StringIO()
        with patch("apple_cli.mail_app.run_osascript", return_value="1\tmid-1\tSubject\tSender\tDate\tAccount\tMailbox\nBody"), redirect_stdout(buffer):
            exit_code = mail_app.main(["messages", "view", "--id", "1", "--json"])
        self.assertEqual(0, exit_code)
        output = buffer.getvalue()
        self.assertIn('"date": "Date"', output)
        self.assertNotIn("date_received", output)

    def test_message_selector_flags_are_mutually_exclusive(self) -> None:
        with self.assertRaises(SystemExit):
            mail_app.main(["messages", "view", "--id", "1", "--message-id", "mid-1"])

    def test_show_message(self) -> None:
        with patch("apple_cli.mail_app.run_osascript") as script_mock:
            exit_code = mail_app.main(["messages", "show", "--id", "123"])
        self.assertEqual(0, exit_code)
        script_mock.assert_called_once()
        self.assertIn("set selected messages of message viewer 1 to {theMessage}", script_mock.call_args[0][0])
        self.assertIn("activate", script_mock.call_args[0][0])

    def test_messages_aliases_work(self) -> None:
        with patch("apple_cli.mail_app.run_osascript", return_value="") as script_mock:
            exit_code = mail_app.main(["msg", "ls"])
        self.assertEqual(0, exit_code)
        self.assertEqual("desc", script_mock.call_args[0][1][3])

    def test_mailboxes_aliases_work(self) -> None:
        with patch("apple_cli.mail_app.run_osascript", return_value="") as script_mock:
            exit_code = mail_app.main(["mboxes", "ls"])
        self.assertEqual(0, exit_code)
        self.assertEqual("", script_mock.call_args[0][1][0])

    def test_mailboxes_remove_aliases_work(self) -> None:
        with patch("apple_cli.mail_app.run_osascript", return_value=""):
            exit_code = mail_app.main(["mbox", "rm", "--account", "iCloud", "--mailbox", "Temp"])
        self.assertEqual(0, exit_code)

    def test_print_rows_hides_message_id_in_text_mode(self) -> None:
        rows = [{"id": "1", "message_id": "mid-1", "subject": "Hello"}]
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            mail_app.print_rows(rows, as_json=False)
        output = buffer.getvalue()
        self.assertIn("id\tsubject", output)
        self.assertNotIn("message_id", output)

    def test_print_rows_keeps_message_id_in_json_mode(self) -> None:
        rows = [{"id": "1", "message_id": "mid-1", "subject": "Hello"}]
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            mail_app.print_rows(rows, as_json=True)
        output = buffer.getvalue()
        self.assertIn('"message_id": "mid-1"', output)

    def test_help_shows_root_description(self) -> None:
        parser = mail_app.make_parser()
        buffer = io.StringIO()
        with redirect_stdout(buffer), self.assertRaises(SystemExit):
            parser.parse_args(["-h"])
        self.assertIn("Apple Mail command-line interface powered by AppleScript.", buffer.getvalue())

    def test_help_shows_subcommand_description(self) -> None:
        parser = mail_app.make_parser()
        buffer = io.StringIO()
        with redirect_stdout(buffer), self.assertRaises(SystemExit):
            parser.parse_args(["messages", "view", "-h"])
        self.assertIn("Show message metadata and content, or output body only.", buffer.getvalue())

    def test_version_flag_prints_version(self) -> None:
        parser = mail_app.make_parser()
        buffer = io.StringIO()
        with redirect_stdout(buffer), self.assertRaises(SystemExit):
            parser.parse_args(["--version"])
        self.assertEqual(f"mail-app {version.__version__}", buffer.getvalue().strip())

    def test_subprocess_failure_returns_nonzero(self) -> None:
        with patch(
            "apple_cli.mail_app.run_osascript",
            side_effect=subprocess.SubprocessError("spawn failed"),
        ):
            code = mail_app.main(["messages", "list"])
        self.assertEqual(1, code)


if __name__ == "__main__":
    unittest.main()
