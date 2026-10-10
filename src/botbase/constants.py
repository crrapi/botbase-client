"""Protocol constants for sys-botbase 2.x.

Values come from sys-botbase's source (util.c, main.c) and libnx's headers
(services/hid.h, services/set.h). Names match what sys-botbase parses on the wire.
"""

DEFAULT_PORT = 6000

# The longest command line sys-botbase accepts (MAX_LINE_LENGTH in util.h: 344 * 32 * 2).
MAX_LINE_LENGTH = 344 * 32 * 2

# Commands that print exactly one reply line. Every other command is silent.
REPLY_COMMANDS = frozenset({
    "peek", "peekMulti", "peekAbsolute", "peekAbsoluteMulti", "peekMain", "peekMainMulti",
    "pointer", "pointerAll", "pointerRelative", "pointerPeek", "pointerPeekMulti",
    "getTitleID", "getTitleVersion", "getSystemLanguage", "getMainNsoBase", "getBuildID",
    "getHeapBase", "isProgramRunning", "pixelPeek", "getVersion", "charge", "fdCount",
    "freezeCount", "game",
})

# Every command sys-botbase 2.6 knows.
ALL_COMMANDS = REPLY_COMMANDS | frozenset({
    "poke", "pokeAbsolute", "pokeMain", "pointerPoke",
    "click", "clickSeq", "clickCancel", "press", "release", "setStick", "detachController",
    "configure",
    "freeze", "unFreeze", "freezeClear", "freezePause", "freezeUnpause",
    "touch", "touchHold", "touchDraw", "touchCancel",
    "key", "keyMod", "keyMulti",
    "screenOff", "screenOn",
})

# Button names sys-botbase accepts. An unknown name is silently pressed as A
# (parseStringToButton falls through to HidNpadButton_A), so clients must validate.
BUTTONS = frozenset({
    "A", "B", "X", "Y", "L", "R", "ZL", "ZR", "PLUS", "MINUS", "LSTICK", "RSTICK",
    "DUP", "DDOWN", "DLEFT", "DRIGHT", "DU", "DD", "DL", "DR",
    "HOME", "CAPTURE",
    "PALMA",   # Poke Ball Plus button
    "UNUSED",  # BIT(20): a dummy input that games ignore, useful to wake the virtual controller
})

# Friendlier aliases this client accepts and translates before sending.
BUTTON_ALIASES = {
    "UP": "DUP", "DOWN": "DDOWN", "LEFT": "DLEFT", "RIGHT": "DRIGHT",
    "+": "PLUS", "-": "MINUS", "START": "PLUS", "SELECT": "MINUS",
    "LS": "LSTICK", "RS": "RSTICK", "L3": "LSTICK", "R3": "RSTICK",
    "SCREENSHOT": "CAPTURE",
}

STICK_MIN, STICK_MAX = -0x8000, 0x7FFF
SCREEN_WIDTH, SCREEN_HEIGHT = 1280, 720

# configure <name> <value>
CONFIG_KEYS = {
    "mainLoopSleepTime": "ms the main loop sleeps after each poll (default 50); sets the per-command latency",
    "buttonClickSleepTime": "ms a button is held during click / clickSeq (default 50)",
    "keySleepTime": "ms a keyboard key is held (default 25)",
    "fingerDiameter": "virtual touch diameter (default 50)",
    "pollRate": "ms per touch / key poll (default 17, about one 60 Hz frame)",
    "freezeRate": "ms between freeze rewrites (default 3)",
    "echoCommands": "1 echoes every command back after its output (default 0)",
    "printDebugResultCodes": "1 prints failing libnx Result codes into the reply stream (default 0)",
    "controllerType": "HidDeviceType of the virtual controller (default 3, Pro Controller); detaches it",
}

# HidDeviceType values (libnx services/hid.h) usable with configure controllerType.
CONTROLLER_TYPES = {
    "joycon-right": 1,   # HidDeviceType_JoyRight1
    "joycon-left": 2,    # HidDeviceType_JoyLeft2
    "pro": 3,            # HidDeviceType_FullKey3 (sys-botbase default)
    "joycon-left-4": 4,
    "joycon-right-5": 5,
    "fullkey-6": 6,
    "famicom-left": 7,   # LarkHvcLeft
    "famicom-right": 8,  # LarkHvcRight
    "nes-left": 9,       # LarkNesLeft
    "nes-right": 10,     # LarkNesRight
    "snes": 11,          # Lucia
    "pokeball": 12,      # Palma
    "fullkey-13": 13,
    "fullkey-15": 15,
    "debugpad": 17,
    "n64": 22,           # Lagon
    "genesis": 28,       # Lager
}

# SetLanguage (libnx services/set.h), as printed by getSystemLanguage.
LANGUAGES = {
    0: "Japanese", 1: "American English", 2: "French", 3: "German", 4: "Italian",
    5: "Spanish", 6: "Chinese", 7: "Korean", 8: "Dutch", 9: "Portuguese", 10: "Russian",
    11: "Taiwanese", 12: "British English", 13: "Canadian French",
    14: "Latin American Spanish", 15: "Simplified Chinese", 16: "Traditional Chinese",
    17: "Brazilian Portuguese",
}

# HidKeyboardKey (libnx services/hid.h). sys-botbase ignores codes below 4 or above 231.
KEYS = {
    **{chr(ord("A") + i): 4 + i for i in range(26)},
    "D1": 30, "D2": 31, "D3": 32, "D4": 33, "D5": 34, "D6": 35, "D7": 36, "D8": 37, "D9": 38, "D0": 39,
    "Return": 40, "Escape": 41, "Backspace": 42, "Tab": 43, "Space": 44, "Minus": 45, "Plus": 46,
    "OpenBracket": 47, "CloseBracket": 48, "Pipe": 49, "Tilde": 50, "Semicolon": 51, "Quote": 52,
    "Backquote": 53, "Comma": 54, "Period": 55, "Slash": 56, "CapsLock": 57,
    **{f"F{i}": 57 + i for i in range(1, 13)},
    "PrintScreen": 70, "ScrollLock": 71, "Pause": 72, "Insert": 73, "Home": 74, "PageUp": 75,
    "Delete": 76, "End": 77, "PageDown": 78, "RightArrow": 79, "LeftArrow": 80, "DownArrow": 81,
    "UpArrow": 82, "NumLock": 83, "NumPadDivide": 84, "NumPadMultiply": 85, "NumPadSubtract": 86,
    "NumPadAdd": 87, "NumPadEnter": 88,
    **{f"NumPad{i}": 89 + (i - 1) for i in range(1, 10)}, "NumPad0": 98, "NumPadDot": 99,
    "Backslash": 100, "Application": 101, "Power": 102, "NumPadEquals": 103,
    **{f"F{i}": 104 + (i - 13) for i in range(13, 25)},
    "LeftControl": 224, "LeftShift": 225, "LeftAlt": 226, "LeftGui": 227,
    "RightControl": 228, "RightShift": 229, "RightAlt": 230, "RightGui": 231,
}

# HidKeyboardModifier bit numbers, as keyMod expects them (it applies BIT(n) itself).
MODIFIER_BITS = {"Control": 0, "Shift": 1, "LeftAlt": 2, "RightAlt": 3, "Gui": 4,
                 "CapsLock": 8, "ScrollLock": 9, "NumLock": 10, "Katakana": 11, "Hiragana": 12}

# US layout: character -> (key code, needs shift)
_UNSHIFTED = {" ": 44, "\n": 40, "\t": 43, "-": 45, "=": 46, "[": 47, "]": 48, "\\": 49,
              ";": 51, "'": 52, "`": 53, ",": 54, ".": 55, "/": 56}
_SHIFTED = {"!": 30, "@": 31, "#": 32, "$": 33, "%": 34, "^": 35, "&": 36, "*": 37, "(": 38,
            ")": 39, "_": 45, "+": 46, "{": 47, "}": 48, "|": 49, ":": 51, '"': 52, "~": 53,
            "<": 54, ">": 55, "?": 56}
US_LAYOUT = {
    **{chr(ord("a") + i): (4 + i, False) for i in range(26)},
    **{chr(ord("A") + i): (4 + i, True) for i in range(26)},
    **{str(d): (30 + (d - 1) % 10, False) for d in range(10)},
    **{c: (k, False) for c, k in _UNSHIFTED.items()},
    **{c: (k, True) for c, k in _SHIFTED.items()},
}
