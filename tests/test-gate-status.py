import json
import subprocess
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
