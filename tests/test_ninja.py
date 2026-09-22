import io
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from lp_profit_bot.ninja import NinjaClient, NinjaError, NoRedirect


class NinjaTests(unittest.TestCase):
    def client(self):
        with patch.dict("os.environ", {"X1_API_KEY": "test-secret"}):
            return NinjaClient()

    def test_missing_key(self):
        with patch.dict("os.environ", {}, clear=True), self.assertRaises(NinjaError):
            NinjaClient()

    def test_authenticated_pool_list(self):
        client = self.client()
        with patch.object(client._opener, "open", return_value=io.BytesIO(b'{"pools": []}')) as request:
            self.assertEqual(client.pools(), {"pools": []})
        sent = request.call_args.args[0]
        self.assertEqual(sent.full_url, "https://api.x1.ninja/v1/pools?limit=10")
        self.assertEqual(sent.get_header("Authorization"), "Bearer test-secret")
        self.assertEqual(request.call_args.kwargs["timeout"], 20)

    def test_error_does_not_expose_key_or_body(self):
        client = self.client()
        error = HTTPError("https://api.x1.ninja", 401, "test-secret", {}, None)
        with patch.object(client._opener, "open", side_effect=error):
            with self.assertRaises(NinjaError) as caught:
                client.pools()
        self.assertNotIn("test-secret", str(caught.exception))

    def test_malformed_responses_rejected(self):
        for body in [b'not-json', b'[]', b'{}']:
            client = self.client()
            with self.subTest(body=body), patch.object(client._opener, "open", return_value=io.BytesIO(body)):
                with self.assertRaises(NinjaError):
                    client.pools()

    def test_invalid_pool_path_never_sent(self):
        client = self.client()
        with patch.object(client._opener, "open") as request:
            with self.assertRaises(NinjaError):
                client.pool("../trades?secret=value")
            request.assert_not_called()

    def test_redirects_disabled(self):
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.com"))
