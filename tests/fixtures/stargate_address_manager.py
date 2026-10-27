from ast import literal_eval
from datetime import datetime
import json
import requests

from stargate_address_book import StargateAddressBook


class StargateAddressManager:
    def __init__(self, stargate):
        self.stargate = stargate
        self.log = stargate.log
        self.cfg = stargate.cfg
        self.net_tools = stargate.net_tools
        self.galaxy = stargate.galaxy
        self.galaxy_path = stargate.galaxy_path
        self.address_book = StargateAddressBook(self, self.galaxy_path)
        self.fan_gates = self.address_book.get_fan_gates()
        self.info_api_url = self.cfg.get("subspace_public_api_url")
        if self.cfg.get("fan_gate_refresh_enable"):
            update_interval = self.cfg.get("fan_gate_refresh_interval")
            stargate.app.schedule.every(update_interval).minutes.do( self.update_fan_gates_from_api )

    def update_fan_gates_from_api(self):
        self.log.log(f"Updating Fan Gates from API: {self.galaxy} Galaxy")
        if self.stargate.net_tools.has_internet_access():
            try:
                request = requests.get(self.info_api_url + "/get_fan_gates.php?galaxy=" + self.galaxy_path, timeout=5)
                request.raise_for_status()
                data = json.loads(request.text)
                for gate_config in data:
                    self.address_book.set_fan_gate(
                        gate_config['name'],
                        literal_eval(gate_config['sg_address']),
                        self.net_tools.get_ip(gate_config['ip']),
                        gate_config['status'],
                    )
                self.cfg.set('fan_gate_last_update', str(datetime.now()))
            except Exception:
                self.log.log("Fan Gate Update: FAILED")
        return self.fan_gates

    def start_lan_gate_discovery(self):
        return None


class StargateAddressValidator:
    pass
