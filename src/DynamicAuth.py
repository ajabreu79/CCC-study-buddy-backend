import hashlib
import time


class DynamicAuth:
    def __init__(self):
        self.step = 30  # seconds window
        self.salt = "xlab_jerry_salt"

    def verify_auth_code(self, received_code):
        current_time_step = int(time.time()) // self.step

        # Check the current, previous, and next time step
        for ts in [current_time_step - 1, current_time_step, current_time_step + 1]:
            expected_key = str(ts) + self.salt
            expected_hash = hashlib.sha256(expected_key.encode()).hexdigest()
            if received_code == expected_hash:
                return True
        return False
