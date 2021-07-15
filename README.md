# Domoticz plugin for Dahua VTO doorbells
_See this [link](https://www.domoticz.com/wiki/Using_Python_plugins) for more information on Domoticz plugins._

Dahua VTO Dz is a plugin, which connects Domoticz to your Dahua VTO doorbell and adds information regarding the doorbell into Domoticz.

## Changelog
- 2021/07/15 (1.0.0): First release

## Software requirements
1. Python version 3.x or higher
2. Domoticz compiled with support for Python-Plugins

## Device support
This plugin is tested the following devices:
- Dahua VTO2202F-P

It might also function with other Dahua VTO devices like VTO1220BW, VTO2000A, VTO2111d-WP, VTO3211D-P2-S1 and VTO3221E. The plugin is not tested with these devices.

## Plugin installation
```
cd domoticz/plugins
git clone https://github.com/rbrouwer/dahua-vto-dz dahua-vto-dz

# restart domoticz
sudo service domoticz.sh restart
```

## Plugin update
```
cd domoticz/plugins/dahua-vto-dz
git pull

# restart domoticz
sudo service domoticz.sh restart
```

## Plugin configuration
Go to `Hardware`, which can be found under `Setup`.
Add new hardware with the type "Dahua VTO Dz".
Fill in the IP address, username and password of your device. If done correctly the 4 devices described in the following section will function.

## Devices
Under `Devices`, which can be found under `Setup`, the plugin will have added 4 devices:

### Doorbell
The doorbell device is a switch, which will be turned on when the doorbell button is pressed. It will turn off when the voip-call is missed or hung up.

### Doorbell (Advanced)
The doorbell (Advanced) devices is selector switch, which will display additional states in addition to the doorbell device.
- It will turn to the state "On" when the call button from the Dahua VTO is pressed.
- It will turn to the state "Calling" when the Dahua VTO has successfully dialed the setup number.
- It will turn to the state "Connected" when the call from the Dahua VTO has been answered/connected.
- It will turn to the state "Off" when the call from the Dahua VTO has either been missed or been hang-up.

### Temper Alarm
The temper alarm is an alert device, which will show No alert when the temper alarm button of the Dahua VTO is pressed and show red "Alert" when the temper alarm button the Dahua VTO is not pressed.

### Door lock
The door lock devices allows you to unlock and lock the door (with door id: 1) by pressing the switch. The plugin will attempt to show the accurate state of the door lock, however the Dahua VTO devices do not send any events when the door lock is closed after the unlock period has expired. The plugin will enforce the configured unlock responding interval and not resend unlock commands until the "unlock responding interval" has expired.

Currently this plugin only supports opening of door lock id #1.

## Known issues
Only door lock #1 is supported.

## Credits
Special thanks to:
- [elad-bar/DahuaVTO2MQTT](https://github.com/elad-bar/DahuaVTO2MQTT)
- [mcw0/Tools](https://github.com/mcw0/Tools)