# Dahua VTO Dz
#
# A plugin for Domoticz, which receives events from Dahua VTO Doorbells and translates those to devices into Domoticz
#
# Author: Robin Brouwer, 2021
#
"""
<plugin key="DahuaVTODz" name="Dahua VTO Dz" author="Robin Brouwer" version="1.0.0" >
    <description>
        <h2>Dahua VTO Dz</h2><br/>
        A plugin for Domoticz, which receives events from Dahua VTO Doorbells and translates those to devices into Domoticz<br/>
    </description>
    <params>
        <param field="Address" label="IP Address" width="200px" required="true"/>
        <param field="Port" label="Connection" required="true" width="200px" default="5000"/>
        <param field="Username" label="Username" width="200px"/>
        <param field="Password" label="Password" width="200px"/>
        <param field="Mode6" label="Debug" width="150px">
            <options>
                <option label="True" value="Debug"/>
                <option label="False" value="Normal" default="true" />
            </options>
        </param>
    </params>
</plugin>
"""

# Main import
import Domoticz

try:
    # noinspection PyUnresolvedReferences
    from Domoticz import Devices, Images, Parameters, Settings
except ImportError:
    pass

from typing import Callable
import struct
import json
import sys
import hashlib
from datetime import datetime, timedelta

class DahuaVTODz:
    enabled = False
    connection = None
    retry_attempts = 3
    retry_attempt_interval_next = 5
    request_id = 1
    session_id = 0
    realm = None
    random = None
    access_control_factory_instance = None
    unlock_interval = None
    unlock_interval_next = None
    keep_alive_interval = None
    keep_alive_interval_next = None
    attached_to_events = False
    data_handlers = {}
    keep_data_handlers = []
    dahua_details = {}
    hold_time = 0
    hold_time_date = None

    def __init__(self):
        return

    def on_start(self):
        if Parameters["Mode6"] == "Debug":
            Domoticz.Debugging(1)
        dump_config_to_log()
        self.setup_devices()
        self.connect()
        Domoticz.Heartbeat(1)

    def setup_devices(self):
        if len(Devices) == 0:
            Domoticz.Device(Name="Doorbell", Unit=1, TypeName="Switch", Switchtype=1).Create()

            options = {"LevelActions": "|||",
                       "LevelNames": "Off|On|Calling|Connected",
                       "LevelOffHidden": "false",
                       "SelectorStyle": "0"
                       }
            Domoticz.Device(Name="Doorbell (Advanced)", Unit=2, TypeName="Selector Switch", Switchtype=18, Image=9,
                            Options=options).Create()

            Domoticz.Device(Name="Temper Alarm", Unit=3, TypeName="Alert", Image=13).Create()

            Domoticz.Device(Name="Door lock", Unit=4, TypeName="Switch", Switchtype=20).Create()

        self.update_device(1, 0, "Off", 1)
        self.update_device(2, 0, str(0), 1)  # Off
        self.update_device(3, 0, "No alert", 1)
        self.update_device(4, 0, "Locked", 1)

    def connect(self):
        self.connection = Domoticz.Connection(Name="DahuaVTO", Transport="TCP/IP", Protocol="None",
                                              Address=Parameters["Address"], Port=Parameters["Port"])
        self.connection.Connect()

    def send(self, action, handler, single_response: bool = True, params=None, instance_id: int = None):
        if params is None:
            params = {}

        self.request_id += 1

        message_data = {
            "id": self.request_id,
            "session": self.session_id,
            "method": action,
            "params": params
        }

        if instance_id is not None:
            message_data["object"] = instance_id

        if handler is not None:
            self.data_handlers[self.request_id] = handler
            if not single_response:
                self.keep_data_handlers.append(self.request_id)

        self.connection.Send(self.convert_message(message_data))

    def disconnect(self):
        self.connection.Disconnect()
        self.connection = None

    def on_connect(self, status, description):
        if status == 0:
            Domoticz.Debug("Connected to Dahua VTO successfully.")
            self.pre_login()
        else:
            Domoticz.Log("Failed to connect (" + str(status) + ") to: " + Parameters["Address"] + ":" + Parameters[
                "Port"] + " with error: " + description)

    def pre_login(self):
        Domoticz.Log("Sending PreLogin package to Dahua VTO")

        request_data = {
            "clientType": "",
            "ipAddr": "(null)",
            "loginType": "Direct",
            "userName": Parameters["Username"],
            "password": ""
        }

        self.send("global.login", self.handle_pre_login, True, request_data)

    def handle_pre_login(self, data):
        error = data.get("error")
        params = data.get("params")

        if error is not None:
            error_message = error.get("message")

            if error_message == "Component error: login challenge!":
                self.random = params.get("random")
                self.realm = params.get("realm")
                self.session_id = data.get("session")

                self.login()

    def login(self):
        Domoticz.Log("Sending login package to Dahua VTO")

        password = self.hash_password(self.random, self.realm, Parameters["Username"], Parameters["Password"])
        request_data = {
            "clientType": "",
            "ipAddr": "(null)",
            "loginType": "Direct",
            "userName": Parameters["Username"],
            "password": password,
            "authorityType": "Default"
        }

        self.send("global.login", self.handle_login, True, request_data)

    def handle_login(self, data):
        result = data.get("result")
        if result:
            Domoticz.Log("Logged into Dahua VTO successfully.")
        else:
            Domoticz.Error("Failed to log into Dahua VTO; Reconnecting in ~30...")
            self.disconnect()
            self.connection = None
            self.keep_alive_interval_next = 30
            return

        params = data.get("params")
        keep_alive_interval = params.get("keepAliveInterval")

        if keep_alive_interval is not None:
            self.keep_alive_interval = keep_alive_interval - 5
            self.keep_alive_interval_next = self.keep_alive_interval

            self.load_device_type()
            self.load_version()
            self.load_serial_number()
            self.load_access_control()
            self.load_access_control_factory_instance()
            self.attach_event_manager()

    def load_device_type(self):
        Domoticz.Log("Getting device type from Dahua VTO")

        self.send("magicBox.getDeviceType", self.handle_device_type)

    def handle_device_type(self, data):
        params = data.get("params")
        device_type = params.get("type")

        self.dahua_details["deviceType"] = device_type

        Domoticz.Log(f"Device Type: {device_type}")

    def load_version(self):
        Domoticz.Log("Getting version from Dahua VTO")

        self.send("magicBox.getSoftwareVersion", self.handle_version)

    def handle_version(self, data):
        params = data.get("params")
        version_details = params.get("version", {})
        version = version_details.get("Version")
        build_date = version_details.get("BuildDate")

        self.dahua_details["version"] = version
        self.dahua_details["buildDate"] = build_date

        Domoticz.Log(f"Version: {version}, Build Date: {build_date}")

    def load_serial_number(self):
        Domoticz.Log("Getting serial number from Dahua VTO")

        request_data = {
            "name": "T2UServer"
        }

        self.send("configManager.getConfig", self.handle_serial_number, True, request_data)

    def handle_serial_number(self, data):
        params = data.get("params")
        table = params.get("table", {})
        serial_number = table.get("UUID")

        self.dahua_details["serialNumber"] = serial_number

        Domoticz.Log(f"Serial Number: {serial_number}")

    def load_access_control(self):
        Domoticz.Log("Getting access control configuration from Dahua VTO")

        request_data = {
            "name": "AccessControl"
        }

        self.send("configManager.getConfig", self.handle_access_control, True, request_data)

    def handle_access_control(self, data):
        params = data.get("params")
        table = params.get("table")

        for item in table:
            access_control = item.get('AccessProtocol')

            if access_control == 'Local':
                self.hold_time = item.get('UnlockReloadInterval')
                self.unlock_interval = item.get('UnlockHoldInterval')

                Domoticz.Log(f"Hold time: {self.hold_time}")
                Domoticz.Log(f"Unlock interval: {self.unlock_interval}")

    def load_access_control_factory_instance(self):
        Domoticz.Log("Getting access control factory instance from Dahua VTO")

        request_data = {
            "Channel": 0
        }

        self.send("accessControl.factory.instance", self.handle_access_control_factory_instance, True, request_data)

    def handle_access_control_factory_instance(self, data):
        result = data.get("result")
        if result:
            Domoticz.Log("Loaded access control factory instance from Dahua VTO")
            self.access_control_factory_instance = result
        else:
            Domoticz.Error("Failed to load access control factory instance from Dahua VTO")
            Domoticz.Log(f"{data}")

    def attach_event_manager(self):
        Domoticz.Log("Subscribing to Dahua's events")

        request_data = {
            "codes": ['All']
        }

        self.update_device(1, Devices[1].nValue, Devices[1].sValue)
        self.update_device(2, Devices[2].nValue, Devices[2].sValue)
        self.update_device(3, Devices[3].nValue, Devices[3].sValue)
        self.update_device(4, Devices[4].nValue, Devices[4].sValue)

        self.send("eventManager.attach", self.handle_notify_event_stream, False, request_data)

    def handle_notify_event_stream(self, data):
        self.attached_to_events = True
        method = data.get("method")
        params = data.get("params")

        if method == "client.notifyEventStream":
            try:
                event_list = params.get("eventList")

                for event in event_list:
                    action = event.get("Action")
                    code = event.get("Code")
                    if Parameters["Mode6"] == "Debug":
                        Domoticz.Debug(f"Got event, action: {action}, code: {code}")
                        Domoticz.Debug(f"{event}")

                    if action == "Pulse" and code == "BackKeyLight":
                        data = event.get("Data")
                        state = data.get('State')
                        self.handle_doorbell_state(state)

                    if action == "Pulse" and code == "AccessControl":
                        data = event.get("Data")
                        command = data.get('Name')
                        self.handle_lock_command(command)

                    if action == "Start" and code == "ProfileAlarmTransmit":
                        self.handle_temper_alert(True)

                    if action == "Stop" and code == "ProfileAlarmTransmit":
                        self.handle_temper_alert(False)

            except Exception as ex:
                exc_type, exc_obj, exc_tb = sys.exc_info()

                Domoticz.Log(f"Failed to handle event, error: {ex}, Line: {exc_tb.tb_lineno}")

    def handle_doorbell_state(self, doorbell_state):
        Domoticz.Log(f"Got BackKeyLight-event, State: {doorbell_state}")
        if doorbell_state == 1:
            self.update_device(1, 1, "On")
            self.update_device(2, 10, str(10))  # On
        elif doorbell_state == 2:
            self.update_device(2, 20, str(20))  # Calling
        elif doorbell_state == 5:
            self.update_device(2, 30, str(30))  # Connected
        else:
            self.update_device(1, 0, "Off")
            self.update_device(2, 0, str(0))  # Off

    def handle_lock_command(self, lock_command):
        Domoticz.Log(f"Got AccessControl-event, Command: {lock_command}")
        if lock_command == "OpenDoor":
            self.update_device(4, 1, "Unlocked")
            self.unlock_interval_next = self.unlock_interval + 1
            if self.hold_time is not None:
                self.hold_time_date = datetime.now() + timedelta(seconds=self.hold_time)
        if lock_command == "CloseDoor":
            self.update_device(4, 0, "Locked")
            self.unlock_interval_next = None

    def handle_temper_alert(self, temper_state: bool):
        if temper_state:
            self.update_device(3, 4, "Alert")
        else:
            self.update_device(3, 0, "No alert")

    @staticmethod
    def update_device(unit, n_value, s_value, timed_out=0, always_update=False):
        # Make sure that the Domoticz device still exists (they can be deleted) before updating it
        if unit in Devices:
            if Devices[unit].nValue != n_value or Devices[unit].sValue != s_value or Devices[
                unit].TimedOut != timed_out or always_update:
                Devices[unit].Update(nValue=n_value, sValue=str(s_value), TimedOut=timed_out)
                Domoticz.Debug(
                    "Update " + Devices[unit].Name + ": " + str(n_value) + " - '" + str(s_value) + "' - " + str(timed_out))

    def keep_alive(self):
        if Parameters["Mode6"] == "Debug":
            Domoticz.Log("Sending keep alive to Dahua VTO successfully.")
        self.keep_alive_interval_next = 3

        request_data = {
            "timeout": self.keep_alive_interval,
            "action": True
        }

        self.send("global.keepAlive", self.handle_keep_alive, True, request_data)

    def handle_keep_alive(self, data):
        result = data.get("result")
        if result:
            if Parameters["Mode6"] == "Debug":
                Domoticz.Log("Received keep alive from Dahua VTO successfully.")
            self.keep_alive_interval_next = self.keep_alive_interval
        else:
            Domoticz.Error("Failed to sent keep alive to Dahua VTO; Reconnecting in ~30...")
            self.disconnect()
            self.connection = None
            self.keep_alive_interval_next = 30
            return

    def handle_retries(self):
        if "deviceType" in self.dahua_details and "version" in self.dahua_details and "buildDate" in self.dahua_details and "serialNumber" in self.dahua_details and self.access_control_factory_instance is not None and self.unlock_interval is not None and self.hold_time is not None:
            Domoticz.Log("Initialized successfully")
            self.retry_attempts = None
            self.retry_attempt_interval_next = None
            return

        Domoticz.Error("Initialization not completed; Retrying failed calls.")
        self.retry_attempts -= 1

        if "deviceType" not in self.dahua_details:
            self.data_handlers = {key: val for key, val in self.data_handlers.items() if val != self.handle_device_type}
            self.load_device_type()

        if "version" not in self.dahua_details or "buildDate" not in self.dahua_details:
            self.data_handlers = {key: val for key, val in self.data_handlers.items() if val != self.handle_version}
            self.load_version()

        if "serialNumber" not in self.dahua_details:
            self.data_handlers = {key: val for key, val in self.data_handlers.items() if val != self.handle_serial_number}
            self.load_serial_number()

        if self.access_control_factory_instance is None:
            self.data_handlers = {key: val for key, val in self.data_handlers.items() if
                                  val != self.handle_access_control_factory_instance}
            self.load_access_control_factory_instance()

        if self.unlock_interval is None or self.hold_time is None:
            self.data_handlers = {key: val for key, val in self.data_handlers.items() if val != self.handle_access_control}
            self.load_access_control()

        self.retry_attempt_interval_next = 5

    def open_door(self, door_index: int = 0):
        if self.access_control_factory_instance is not None and (
                self.hold_time_date is None or self.hold_time_date < datetime.now()):
            Domoticz.Log(
                "Sending open door command to Dahua VTO with instance: {}".format(self.access_control_factory_instance))

            request_data = {
                "DoorIndex": door_index,
                "Type": "",
                "UserID": "",
            }

            self.send("accessControl.openDoor", self.handle_open_door, True, request_data,
                      self.access_control_factory_instance)
        elif self.hold_time_date is not None and self.hold_time_date >= datetime.now():
            Domoticz.Error(
                "Not sending open door command to Dahua VTO, because lock is still on-hold")
        else:
            Domoticz.Log(
                "Failed sending open door command to Dahua VTO, because missing Access Control Factory Instance")

    @staticmethod
    def handle_open_door(data):
        result = data.get("result")
        if result:
            Domoticz.Log("Sent open door command to Dahua VTO successfully")
        else:
            Domoticz.Error("Failed to sent open door command to Dahua VTO")
            Domoticz.Log(f"{data}")

    def close_door(self, door_index: int = 0):
        if self.access_control_factory_instance is not None:
            Domoticz.Log(
                "Sending close door command to Dahua VTO with instance: {}".format(self.access_control_factory_instance))

            request_data = {
                "DoorIndex": door_index,
                "Type": "",
                "UserID": "",
            }

            self.send("accessControl.closeDoor", self.handle_close_door, True, request_data,
                      self.access_control_factory_instance)
        else:
            Domoticz.Log(
                "Failed sending open door command to Dahua VTO, because missing Access Control Factory Instance")

    def handle_close_door(self, data):
        result = data.get("result")
        if result:
            Domoticz.Log("Sent close door command to Dahua VTO successfully")
            # No event is triggered by this, so apply changes locally directly
            self.update_device(4, 0, "Locked")
            self.unlock_interval_next = None
        else:
            Domoticz.Error("Failed to sent close door command to Dahua VTO")
            Domoticz.Log(f"{data}")

    def on_message(self, data):
        message = self.parse_response(data)

        if message is None:
            if Parameters["Mode6"] == "Debug":
                Domoticz.Log("Unparseable data message received: {data}")
            return

        message_id = message.get("id")

        handler: Callable = self.data_handlers.get(message_id, self.handle_default)
        handler(message)

        if message_id not in self.keep_data_handlers:
            self.data_handlers.pop(message_id, None)

    @staticmethod
    def handle_default(data):
        Domoticz.Log(f"Data received without handler: {data}")

    def on_disconnect(self):
        Domoticz.Error("Got disconnected from Dahua VTO; Reconnecting in ~30...")
        self.connection = None
        self.reset_params()
        self.keep_alive_interval_next = 30
        self.update_device(1, Devices[1].nValue, Devices[1].sValue, 1)
        self.update_device(2, Devices[2].nValue, Devices[2].sValue, 1)
        self.update_device(3, Devices[3].nValue, Devices[3].sValue, 1)
        self.update_device(4, Devices[4].nValue, Devices[4].sValue, 1)

    def on_heartbeat(self):
        if self.connection is not None and self.connection.Connected() and self.retry_attempts is not None and self.retry_attempts > 0 and self.retry_attempt_interval_next is not None:
            self.retry_attempt_interval_next -= 1
            if self.retry_attempt_interval_next <= 0:
                self.handle_retries()

        if self.connection is not None and self.connection.Connected() and self.keep_alive_interval_next is not None:
            self.keep_alive_interval_next -= 1
            if self.keep_alive_interval_next <= 0:
                self.keep_alive()
        elif self.keep_alive_interval_next is not None and self.keep_alive_interval_next > 0:
            self.keep_alive_interval_next -= 1
            if self.keep_alive_interval_next <= 0:
                self.keep_alive_interval_next = None
                self.connect()

        if self.unlock_interval_next is not None:
            self.unlock_interval_next -= 1
            if self.unlock_interval_next <= 0:
                self.unlock_interval_next = None
                self.update_device(4, 0, "Locked")

    def on_command(self, unit, command, level, color):
        Domoticz.Debug("onCommand: " + command + ", level (" + str(level) + ") Color:" + color)
        if unit == 4 and command == "On":
            self.open_door()

        if unit == 4 and command == "Off":
            self.close_door()

    def reset_params(self):
        self.retry_attempts = 3
        self.retry_attempt_interval_next = 5
        self.request_id = 1
        self.session_id = 0
        self.realm = None
        self.random = None
        self.access_control_factory_instance = None
        self.unlock_interval = None
        self.unlock_interval_next = None
        self.keep_alive_interval = None
        self.keep_alive_interval_next = None
        self.data_handlers = {}
        self.keep_data_handlers = []
        self.dahua_details = {}
        self.hold_time = 0
        self.hold_time_date = None

    @staticmethod
    def parse_response(response):
        result = None

        try:
            response_parts = str(response).split("\\x00")
            for responsePart in response_parts:
                if responsePart.startswith("{"):
                    end = responsePart.rindex("}") + 1
                    message = responsePart[0:end]

                    result = json.loads(message)

        except Exception as e:
            exc_type, exc_obj, exc_tb = sys.exc_info()

            Domoticz.Log(f"Failed to read data: {response}, error: {e}, Line: {exc_tb.tb_lineno}")

        return result

    @staticmethod
    def convert_message(data):
        message_data = json.dumps(data, indent=4)

        header = struct.pack(">L", 0x20000000)
        header += struct.pack(">L", 0x44484950)
        header += struct.pack(">d", 0)
        header += struct.pack("<L", len(message_data))
        header += struct.pack("<L", 0)
        header += struct.pack("<L", len(message_data))
        header += struct.pack("<L", 0)

        message = header + message_data.encode("utf-8")

        return message

    @staticmethod
    def hash_password(random, realm, username, password):
        password_str = f"{username}:{realm}:{password}"
        password_bytes = password_str.encode('utf-8')
        password_hash = hashlib.md5(password_bytes).hexdigest().upper()

        random_str = f"{username}:{random}:{password_hash}"
        random_bytes = random_str.encode('utf-8')
        random_hash = hashlib.md5(random_bytes).hexdigest().upper()

        return random_hash


_plugin = DahuaVTODz()


# noinspection PyPep8Naming
def onStart():
    global _plugin
    _plugin.on_start()

# noinspection PyPep8Naming PyUnusedLocal
def onConnect(Connection, Status, Description):
    global _plugin
    _plugin.on_connect(Status, Description)

# noinspection PyPep8Naming
def onMessage(Connection, Data):
    global _plugin
    _plugin.on_message(Data)

# noinspection PyPep8Naming PyUnusedLocal
def onDisconnect(Connection):
    global _plugin
    _plugin.on_disconnect()

# noinspection PyPep8Naming
def onHeartbeat():
    global _plugin
    _plugin.on_heartbeat()


# executed each time we click on device thru Domoticz GUI
# noinspection PyPep8Naming
def onCommand(Unit, Command, Level, Color):
    global _plugin
    _plugin.on_command(Unit, Command, Level, Color)


# Generic helper functions
def dump_config_to_log():
    for x in Parameters:
        if Parameters[x] != "":
            Domoticz.Debug("'" + x + "':'" + str(Parameters[x]) + "'")
    Domoticz.Debug("Device count: " + str(len(Devices)))
    for x in Devices:
        Domoticz.Debug("Device:           " + str(x) + " - " + str(Devices[x]))
        Domoticz.Debug("Device ID:       '" + str(Devices[x].ID) + "'")
        Domoticz.Debug("Device Name:     '" + Devices[x].Name + "'")
        Domoticz.Debug("Device nValue:    " + str(Devices[x].nValue))
        Domoticz.Debug("Device sValue:   '" + Devices[x].sValue + "'")
        Domoticz.Debug("Device LastLevel: " + str(Devices[x].LastLevel))
    return