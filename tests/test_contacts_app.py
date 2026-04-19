import io
import subprocess
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from apple_cli import contacts_app


class ContactsAppTests(unittest.TestCase):
    def test_main_no_args_shows_help(self) -> None:
        buffer = io.StringIO()
        with redirect_stderr(buffer):
            exit_code = contacts_app.main([])
        self.assertEqual(1, exit_code)
        output = buffer.getvalue()
        self.assertIn("usage:", output)
        self.assertIn("contacts-app", output)

    def test_run_osascript_success(self) -> None:
        completed = SimpleNamespace(returncode=0, stdout="ok\n", stderr="")
        with patch("apple_cli.contacts_app.subprocess.run", return_value=completed) as run_mock:
            output = contacts_app.run_osascript("script", ["arg1"])
        self.assertEqual("ok", output)
        self.assertEqual(["osascript", "-s", "h", "-", "arg1"], run_mock.call_args.args[0])

    def test_run_osascript_error(self) -> None:
        completed = SimpleNamespace(returncode=1, stdout="", stderr="script failed")
        with patch("apple_cli.contacts_app.subprocess.run", return_value=completed):
            with self.assertRaises(contacts_app.ContactsAppError):
                contacts_app.run_osascript("script", [])

    def test_run_osascript_timeout(self) -> None:
        with patch(
            "apple_cli.contacts_app.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=30),
        ):
            with self.assertRaises(contacts_app.ContactsAppError):
                contacts_app.run_osascript("script", [])

    def test_contacts_list_defaults(self) -> None:
        with patch("apple_cli.contacts_app.list_contacts", return_value=[]) as list_mock:
            exit_code = contacts_app.main(["contacts", "list"])
        self.assertEqual(0, exit_code)
        self.assertEqual("", list_mock.call_args.args[0])  # search
        self.assertEqual("", list_mock.call_args.args[1])  # group
        self.assertEqual(contacts_app.DEFAULT_LIST_LIMIT, list_mock.call_args.args[2])
        self.assertEqual("asc", list_mock.call_args.args[3])

    def test_view_contact(self) -> None:
        buffer = io.StringIO()
        # id, first_name, last_name, organization, job_title, nickname, birth_date, note, emails, phones, urls (11 columns)
        mock_output = "1\tJohn\tDoe\tApple\tEngineer\tJohnny\t1990-01-01\tNote\tjohn@doe.com\t555-1234\thttp://doe.com"
        with patch(
            "apple_cli.contacts_app.run_osascript",
            return_value=mock_output,
        ), redirect_stdout(buffer):
            exit_code = contacts_app.main(["contacts", "view", "--id", "1"])
        self.assertEqual(0, exit_code)
        output = buffer.getvalue()
        self.assertIn("id: 1", output)
        self.assertIn("first name: John", output)
        self.assertIn("last name: Doe", output)
        self.assertIn("birth date: 1990-01-01", output)
        self.assertIn("job title: Engineer", output)

    def test_show_contact(self) -> None:
        with patch("apple_cli.contacts_app.run_osascript") as script_mock:
            exit_code = contacts_app.main(["contacts", "show", "--id", "123"])
        self.assertEqual(0, exit_code)
        script_mock.assert_called_once()
        self.assertIn("show p", script_mock.call_args[0][0])
        self.assertIn("activate", script_mock.call_args[0][0])

    def test_subprocess_failure_returns_nonzero(self) -> None:
        with patch("apple_cli.contacts_app.run_osascript", side_effect=subprocess.SubprocessError("spawn failed")):
            code = contacts_app.main(["contacts", "list"])
        self.assertEqual(1, code)


if __name__ == "__main__":
    unittest.main()
