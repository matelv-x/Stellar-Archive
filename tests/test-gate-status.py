import json
import importlib.util
import subprocess
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import patch_v4_gate_status


ROOT = Path(__file__).resolve().parents[1]


class GateStatusPatchTests(unittest.TestCase):
    def test_original_address_book_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "address_book.js"
            target.write_text(
                (ROOT / "tests/fixtures/address_book.js").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            patch_v4_gate_status.patch_address_js(target)
            script = r"""
const fs=require('fs'),vm=require('vm');
const context={};
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
function check(entry,local,fresh){
  context.stellarArchiveLocalAddress=local;
  context.stellarArchiveStatusFreshness={stale:!fresh};
  return context.stellarArchiveGateIsOnline(entry);
}
console.log(JSON.stringify({
  freshStandard:check({type:'standard',gate_address:[9]},[],true),
  staleStandard:check({type:'standard',gate_address:[9]},[],false),
  freshFan:check({type:'fan',gate_address:[8],is_gate_online:1},[],true),
  staleFan:check({type:'fan',gate_address:[8],is_gate_online:1},[],false),
  staleLan:check({type:'lan',gate_address:[7],is_gate_online:1},[],false),
  local:check({type:'fan',gate_address:[1,2,3]},[1,2,3],false)
}));
"""
            result = subprocess.run(
                ["node", "-e", script, str(target)],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                json.loads(result.stdout),
                {
                    "freshStandard": True,
                    "staleStandard": False,
                    "freshFan": True,
                    "staleFan": False,
                    "staleLan": True,
                    "local": True,
                },
            )

    def test_directory_failure_retries_with_bounded_backoff_and_recovers(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "stargate_address_manager.py"
            target.write_text(
                (ROOT / "tests/fixtures/stargate_address_manager.py").read_text(
                    encoding="utf-8"
                ),
                encoding="utf-8",
            )
            self.assertTrue(patch_v4_gate_status.patch_address_manager(target))
            self.assertFalse(patch_v4_gate_status.patch_address_manager(target))
            compile(target.read_text(encoding="utf-8"), str(target), "exec")

            address_book_module = types.ModuleType("stargate_address_book")
            requests_module = types.ModuleType("requests")
            requests_module.get = lambda *_args, **_kwargs: None

            class FakeBook:
                def __init__(self, *_args):
                    self.updated = []

                def get_fan_gates(self):
                    return {}

                def set_fan_gate(self, *values):
                    self.updated.append(values)

            address_book_module.StargateAddressBook = FakeBook
            previous = sys.modules.get("stargate_address_book")
            previous_requests = sys.modules.get("requests")
            sys.modules["stargate_address_book"] = address_book_module
            sys.modules["requests"] = requests_module
            try:
                spec = importlib.util.spec_from_file_location("retry_manager", target)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
            finally:
                if previous is None:
                    del sys.modules["stargate_address_book"]
                else:
                    sys.modules["stargate_address_book"] = previous
                if previous_requests is None:
                    del sys.modules["requests"]
                else:
                    sys.modules["requests"] = previous_requests

            class Config:
                values = {
                    "subspace_public_api_url": "https://example.invalid",
                    "fan_gate_refresh_enable": True,
                    "fan_gate_refresh_interval": 30,
                }

                def get(self, key):
                    return self.values.get(key)

                def set(self, key, value):
                    self.values[key] = value

            class ScheduleJob:
                @property
                def minutes(self):
                    return self

                def do(self, callback):
                    callbacks.append(callback)

            class Schedule:
                def every(self, _interval):
                    return ScheduleJob()

            class Response:
                def __init__(self, text):
                    self.text = text

                def raise_for_status(self):
                    return None

            callbacks = []
            log_messages = []
            stargate = types.SimpleNamespace(
                log=types.SimpleNamespace(log=log_messages.append),
                cfg=Config(),
                net_tools=types.SimpleNamespace(
                    has_internet_access=lambda: True,
                    get_ip=lambda value: value,
                ),
                galaxy="Milky Way",
                galaxy_path="milkyway",
                app=types.SimpleNamespace(schedule=Schedule()),
            )
            manager = module.StargateAddressManager(stargate)
            self.assertEqual(len(callbacks), 2)

            module.requests.get = lambda *_args, **_kwargs: Response("not json")
            expected_delays = [2, 4, 8, 15, 15]
            for expected in expected_delays:
                manager.update_fan_gates_from_api()
                self.assertEqual(
                    manager._fan_directory_retry_delay_minutes, expected
                )
                self.assertIsNotNone(manager._fan_directory_retry_at)

            before = len(log_messages)
            manager.retry_fan_gates_from_api()
            self.assertEqual(len(log_messages), before)

            payload = json.dumps(
                [{"name": "Test", "sg_address": "[1, 2, 3]", "ip": "host", "status": "1"}]
            )
            module.requests.get = lambda *_args, **_kwargs: Response(payload)
            manager._fan_directory_retry_at = datetime.now() - timedelta(seconds=1)
            manager.retry_fan_gates_from_api()
            self.assertEqual(manager._fan_directory_retry_delay_minutes, 0)
            self.assertIsNone(manager._fan_directory_retry_at)
            self.assertIsNone(manager._fan_directory_error)
            self.assertEqual(manager.address_book.updated[0][0], "Test")
            self.assertIn("fan_gate_last_update", manager.cfg.values)

            stargate.net_tools.has_internet_access = lambda: False
            manager.update_fan_gates_from_api()
            self.assertEqual(manager._fan_directory_error, "NoInternetAccess")
            self.assertEqual(manager._fan_directory_retry_delay_minutes, 2)


if __name__ == "__main__":
    unittest.main()
