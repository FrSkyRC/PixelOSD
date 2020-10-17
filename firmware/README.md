FrSky Pixel OSD Firmware Upgrades
=================================

Flashing any upgrade to your OSD is totally risk free. The bootloader
in the FrSky OSD will perform several integrity verifications, and
even interrupting the upgrade process in the middle can be easily
recovered. Worst case scenario, your OSD will boot in permanent
bootloader mode and wait for you to flash an upgrade file to it
using the [FrSky OSD App](https://github.com/FrSkyRC/FrSkyOSDApp/releases).

If you find any dealbreaker bugs in a new version, downgrading back to the
previous version until the next version is released is also supported and easy.

To change the firmware in your FrSky Pixel OSD use the following
steps:

- Download the [FrSky OSD app](https://github.com/FrSkyRC/FrSkyOSDApp/releases).
- If your OSD is installed into a flight controller, just connect it
  via USB and make sure the OSD is powered.
- If your OSD is not yet installed, your can connect it directly to
  the computer using an USB-to-UART adapter.
- In the FrSky OSD app, select the appropriate port for your FC or OSD
  and click on `Connect`.
- Once the OSD is connected, the `Flash Firmware` button will be
  enabled.
- Click on it and you'll be presented with a list of the available
  firmwares. Next to each firmware there's a button with an `ⓘ` that
  will show you the changelog for that specific release.
- Any firmware version, either an upgrade or a downgrade can be
  flashed at any time.
- When changing between major firmware versions you might need to
  reupload any fonts stored in the OSD, since their internal
  representation might change.

In case of an unlikely catastrophic failure (like the firmware
booting and entering and endless loop that wouldn't let do you
do anything, not even flash) that wasn't caught by us before
releasing the firmware to the public, the OSD has a builtin last
resort recovery mechanism that forces it to enter bootloader mode and
from there it can always be flashed. To trigger it unpower the OSD,
disconnect any camera and VTX/screen that might be connected to it,
hold the `VIDEO_IN` and `VIDEO_OUT` pins shorted together and power
only the OSD up. This will force it to stay in bootloader mode and
then you can use the app as if you were flashing it from a working
firmware.

### Alternative flashing methods

If the FrSky OSD app doesn't run on your system, you can flash new
firmwares manually using the Python SDK.

Download [frskyosd.py](../sdk/python/frskyosd/frskyosd.py]) and the
`.bin` file for the firmware that you want to flash from this
directory. With both downloaded to the same directory, run:

```sh
python frskyosd.py --flash FrSkyOSD-vx.y.z_YYYYMMDD.bin <COM-port>
```

If it finishes without printing any error messages, the firmware was
succesfully flashed to the OSD.
