# Phone mouse

Bluetooth half of PhoneAgent. The PC shows up to the iPhone as a Bluetooth mouse, so
programs on the PC can move the pointer and tap. Nothing is installed on the phone
and no Apple ID is needed. PhoneAgent's start script launches this folder for you;
these bats also work on their own.

How it works: Windows can't pretend to be a Bluetooth mouse, but Linux can. usbipd
hands the PC's Bluetooth chip to Ubuntu running in WSL, where `bt_mouse.py` runs
BlueZ as a mouse. Windows programs send it commands on 127.0.0.1:7777.

1. **Set up phone mouse.bat**: once. Installs usbipd, Ubuntu and BlueZ.
2. **Start phone mouse.bat**: each time. First time, pair from the iPhone
   (AssistiveTouch on, then Settings > Bluetooth > Phone Mouse).
3. **Test mouse.bat**: moves the pointer around.
4. **Give Bluetooth back to Windows.bat**: stops it. Windows has no Bluetooth while the mouse runs.

On the iPhone, under Settings > Accessibility > Pointer Control, turn off
"Automatically Hide Pointer" so the pointer stays visible.

Commands (one per line, each answers one line): `status`, `move DX DY [STEP MS]`,
`home`, `down`, `up`, `click`, `scroll N`, `pace STEP MS`, `quit`.
