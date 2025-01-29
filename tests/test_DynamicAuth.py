import unittest
import hashlib
import time
from src.DynamicAuth import DynamicAuth


class TestDynamicAuth(unittest.TestCase):
    def setUp(self):
        self.step = 30
        self.salt = "xlab_jerry_salt"

    def test_verify_auth_code(self):
        current_time_step = int(time.time()) // self.step
        expected_key = str(current_time_step) + self.salt
        expected_hash = hashlib.sha256(expected_key.encode()).hexdigest()

        verify_auth_code = DynamicAuth().verify_auth_code

        # Test with correct hash
        self.assertTrue(verify_auth_code(expected_hash))

        # Test with incorrect hash
        self.assertFalse(verify_auth_code("incorrect_hash"))
