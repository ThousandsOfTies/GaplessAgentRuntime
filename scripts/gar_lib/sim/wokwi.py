"""Wokwi simulation target implementation for ESP32/M5Stack-class boards."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from scripts.gar_lib._config import PROJECT_ROOT
from scripts.gar_lib.environments.base import DevEnvironment
from scripts.gar_lib.sim.base import SimCommandBuilder, SimProvider

DEFAULT_WOKWI_DIR = PROJECT_ROOT / ".gar" / "wokwi" / "m5stackc"
DEFAULT_TIMEOUT_MS = 30000


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    if not raw:
        return default
    return Path(raw).expanduser().resolve()


def _is_pid_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class WokwiSimCommandBuilder(SimCommandBuilder):
    """Generates local shell commands for Wokwi simulation operations."""

    def build_gpio_systemd_install(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
        return ":"

    def build_sim_diag_json(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
        return "gar sim env diag --json"

    def build_gpio_sim_setup(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
        return ":"

    def build_gpio_sim_teardown(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
        return ":"

    def build_systemd_install(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
        return ":"

    def build_systemd_start(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
        return "wokwi-cli ."

    def build_systemd_stop(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
        return ":"

    def build_sim_start(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
        return "wokwi-cli ."

    def build_sim_stop(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
        return ":"

    def build_sim_status(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
        return "gar sim env status --json"

    def build_sim_log(self) -> str:
        return "tail -f .gar/wokwi/m5stackc/wokwi.log"

    def build_gpio_runtime_status(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
        return "gar sim env status --json"

    def build_panel(self, action: str, params: dict) -> str:
        return ":"


class WokwiSimProvider(SimProvider):
    """High-level Wokwi simulation operations.

    The provider creates a local Wokwi project for an M5StickC/M5StackC-style
    ESP32 setup. If `wokwi-cli` and firmware are available it starts the CLI in
    the background; otherwise it still leaves a ready-to-fill project on disk.
    """

    def __init__(self, dev_env: type[DevEnvironment], host: str | None = None):
        self.dev_env = dev_env
        self.host = host
        self.builder = WokwiSimCommandBuilder()
        self.project_dir = _env_path("GAR_WOKWI_PROJECT_DIR", DEFAULT_WOKWI_DIR)
        self.state_path = self.project_dir / "state.json"
        self.log_path = self.project_dir / "wokwi.log"

    def _print_payload(self, payload: dict, *, json_output: bool = False) -> None:
        if json_output:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return
        for key, value in payload.items():
            if isinstance(value, dict | list):
                value = json.dumps(value, ensure_ascii=False)
            print(f"{key}: {value}")

    def _firmware_path(self) -> str:
        return os.environ.get("GAR_WOKWI_FIRMWARE", ".pio/build/m5stackc/firmware.bin")

    def _elf_path(self) -> str:
        return os.environ.get("GAR_WOKWI_ELF", ".pio/build/m5stackc/firmware.elf")

    def _timeout_ms(self) -> int:
        raw = os.environ.get("GAR_WOKWI_TIMEOUT_MS")
        if raw is None:
            return DEFAULT_TIMEOUT_MS
        try:
            return max(0, int(raw))
        except ValueError:
            return DEFAULT_TIMEOUT_MS

    def _state(self) -> dict:
        if not self.state_path.exists():
            return {}
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_state(self, payload: dict) -> None:
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _relative_path_exists(self, path_text: str) -> bool:
        path = Path(path_text)
        if not path.is_absolute():
            path = self.project_dir / path
        return path.exists()

    def _write_if_missing(self, name: str, content: str) -> None:
        path = self.project_dir / name
        if path.exists():
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _ensure_project(self, hw_definition: dict[str, list[dict[str, str]]]) -> None:
        del hw_definition
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self._write_if_missing("diagram.json", json.dumps(self._default_diagram(), ensure_ascii=False, indent=2) + "\n")
        self._write_if_missing("wokwi.toml", self._default_wokwi_toml())
        self._write_if_missing("platformio.ini", self._default_platformio_ini())
        self._write_if_missing("src/main.cpp", self._default_main_cpp())
        self._write_if_missing("lib/M5Unified/src/M5Unified.h", self._default_m5unified_shim())
        self._write_if_missing("README.md", self._default_readme())

    def prepare_project(self, hw_definition: dict[str, list[dict[str, str]]], *, json_output: bool = False) -> int:
        self._ensure_project(hw_definition)
        self._print_payload(
            {
                "provider": "wokwi",
                "status": "project-ready",
                "project_dir": str(self.project_dir),
                "diagram": str(self.project_dir / "diagram.json"),
                "wokwi_toml": str(self.project_dir / "wokwi.toml"),
                "ok": True,
            },
            json_output=json_output,
        )
        return 0

    def _default_diagram(self) -> dict:
        return {
            "version": 1,
            "author": "Gapless Agent Runtime",
            "editor": "wokwi",
            "parts": [
                {"type": "wokwi-esp32-devkit-v1", "id": "esp", "top": -35.0, "left": -10.0, "attrs": {}},
                {"type": "wokwi-ili9341", "id": "lcd", "top": -55.0, "left": 290.0, "attrs": {}},
                {"type": "wokwi-pushbutton", "id": "btnA", "top": 265.0, "left": 300.0, "attrs": {"color": "red", "bounce": "0"}},
                {"type": "wokwi-pushbutton", "id": "btnB", "top": 265.0, "left": 380.0, "attrs": {"color": "gray", "bounce": "0"}},
                {"type": "wokwi-led", "id": "led", "top": 265.0, "left": 475.0, "attrs": {"color": "red"}},
                {"type": "wokwi-resistor", "id": "r1", "top": 302.0, "left": 502.0, "rotate": 0, "attrs": {"value": "1000"}},
                {"type": "wokwi-gnd", "id": "gnd", "top": 355.0, "left": 370.0, "attrs": {}},
            ],
            "connections": [
                ["esp:TX0", "$serialMonitor:RX", "", []],
                ["esp:RX0", "$serialMonitor:TX", "", []],
                ["lcd:VCC", "esp:3V3", "red", []],
                ["lcd:GND", "esp:GND.1", "black", []],
                ["lcd:SCK", "esp:D13", "green", []],
                ["lcd:MOSI", "esp:D15", "green", []],
                ["lcd:CS", "esp:D5", "green", []],
                ["lcd:D/C", "esp:D23", "green", []],
                ["lcd:RST", "esp:D18", "green", []],
                ["btnA:1.l", "esp:D32", "green", []],
                ["btnA:2.r", "gnd:GND", "black", []],
                ["btnB:1.l", "esp:D33", "green", []],
                ["btnB:2.r", "gnd:GND", "black", []],
                ["led:A", "r1:1", "green", []],
                ["r1:2", "esp:D2", "green", []],
                ["led:C", "gnd:GND", "black", []],
            ],
            "dependencies": {},
        }

    def _default_wokwi_toml(self) -> str:
        return (
            "[wokwi]\n"
            "version = 1\n"
            f"firmware = '{self._firmware_path()}'\n"
            f"elf = '{self._elf_path()}'\n"
            "rfc2217ServerPort = 4000\n"
        )

    def _default_platformio_ini(self) -> str:
        return (
            "[env:m5stackc]\n"
            "platform = espressif32\n"
            "board = m5stick-c\n"
            "framework = arduino\n"
            "monitor_speed = 115200\n"
            "lib_deps =\n"
            "  adafruit/Adafruit ILI9341\n"
        )

    def _default_main_cpp(self) -> str:
        return """#include <M5Unified.h>

void setup() {
  auto cfg = M5.config();
  M5.begin(cfg);
  Serial.begin(115200);
  M5.Display.setRotation(1);
  M5.Display.fillScreen(TFT_BLACK);
  M5.Display.setTextColor(TFT_GREEN, TFT_BLACK);
  M5.Display.setTextSize(2);
  M5.Display.setCursor(8, 12);
  M5.Display.println("GAR Wokwi");
  M5.Display.println("M5StackC");
  Serial.println("GAR Wokwi M5StackC ready");
}

void loop() {
  M5.update();
  if (M5.BtnA.wasPressed()) {
    Serial.println("Button A");
    M5.Display.fillRect(8, 64, 140, 24, TFT_BLACK);
    M5.Display.setCursor(8, 64);
    M5.Display.print("Button A");
  }
  if (M5.BtnB.wasPressed()) {
    Serial.println("Button B");
    M5.Display.fillRect(8, 64, 140, 24, TFT_BLACK);
    M5.Display.setCursor(8, 64);
    M5.Display.print("Button B");
  }
  delay(20);
}
"""

    def _default_m5unified_shim(self) -> str:
        return """#pragma once

#include <Arduino.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ILI9341.h>
#include <SPI.h>

#define TFT_BLACK ILI9341_BLACK
#define TFT_GREEN ILI9341_GREEN
#define TFT_YELLOW ILI9341_YELLOW
#define TFT_ORANGE ILI9341_ORANGE
#define TFT_CYAN ILI9341_CYAN
#define TFT_RED ILI9341_RED
#define TFT_WHITE ILI9341_WHITE
#define TFT_NAVY ILI9341_NAVY
#define TFT_DARKGREY 0x7BEF
#define TFT_LIGHTGREY 0xC618

namespace gar_wokwi_m5 {

constexpr int TFT_SCK_PIN = 13;
constexpr int TFT_MOSI_PIN = 15;
constexpr int TFT_CS_PIN = 5;
constexpr int TFT_DC_PIN = 23;
constexpr int TFT_RST_PIN = 18;
constexpr int BUTTON_A_PIN = 32;
constexpr int BUTTON_B_PIN = 33;

class DisplayShim {
 public:
  DisplayShim() : tft_(TFT_CS_PIN, TFT_DC_PIN, TFT_RST_PIN) {}

  void begin() {
    SPI.begin(TFT_SCK_PIN, -1, TFT_MOSI_PIN, TFT_CS_PIN);
    tft_.begin();
  }

  void setRotation(uint8_t rotation) {
    rotation_ = rotation;
    tft_.setRotation(rotation);
  }

  int16_t width() const { return LOGICAL_WIDTH; }
  int16_t height() const { return LOGICAL_HEIGHT; }

  void setBrightness(uint8_t brightness) { brightness_ = brightness; }
  void fillScreen(uint16_t color) { tft_.fillRect(VIEW_X, VIEW_Y, LOGICAL_WIDTH * SCALE, LOGICAL_HEIGHT * SCALE, color); }
  void setTextColor(uint16_t color, uint16_t background) { tft_.setTextColor(color, background); }
  void setTextSize(uint8_t size) {
    textSize_ = size;
    tft_.setTextSize(size * SCALE);
  }
  void setCursor(int16_t x, int16_t y) { tft_.setCursor(mapX(x), mapY(y)); }
  void fillRect(int16_t x, int16_t y, int16_t w, int16_t h, uint16_t color) {
    tft_.fillRect(mapX(x), mapY(y), w * SCALE, h * SCALE, color);
  }
  void drawPixel(int16_t x, int16_t y, uint16_t color) { tft_.fillRect(mapX(x), mapY(y), SCALE, SCALE, color); }
  void drawFastHLine(int16_t x, int16_t y, int16_t w, uint16_t color) { fillRect(x, y, w, 1, color); }
  void drawFastVLine(int16_t x, int16_t y, int16_t h, uint16_t color) { fillRect(x, y, 1, h, color); }
  void drawRect(int16_t x, int16_t y, int16_t w, int16_t h, uint16_t color) {
    drawFastHLine(x, y, w, color);
    drawFastHLine(x, y + h - 1, w, color);
    drawFastVLine(x, y, h, color);
    drawFastVLine(x + w - 1, y, h, color);
  }
  void drawRoundRect(int16_t x, int16_t y, int16_t w, int16_t h, int16_t radius, uint16_t color) {
    tft_.drawRoundRect(mapX(x), mapY(y), w * SCALE, h * SCALE, radius * SCALE, color);
  }
  void fillRoundRect(int16_t x, int16_t y, int16_t w, int16_t h, int16_t radius, uint16_t color) {
    tft_.fillRoundRect(mapX(x), mapY(y), w * SCALE, h * SCALE, radius * SCALE, color);
  }
  void fillCircle(int16_t x, int16_t y, int16_t radius, uint16_t color) {
    tft_.fillCircle(mapX(x), mapY(y), radius * SCALE, color);
  }
  void drawString(const String &text, int16_t x, int16_t y) {
    tft_.setCursor(mapX(x), mapY(y));
    tft_.print(text);
  }
  void drawString(const char *text, int16_t x, int16_t y) {
    tft_.setCursor(mapX(x), mapY(y));
    tft_.print(text);
  }

  template <typename T>
  size_t print(const T &value) {
    return tft_.print(value);
  }

  template <typename T>
  size_t println(const T &value) {
    return tft_.println(value);
  }

 private:
  static constexpr int16_t LOGICAL_WIDTH = 160;
  static constexpr int16_t LOGICAL_HEIGHT = 80;
  static constexpr int16_t SCALE = 2;
  static constexpr int16_t VIEW_X = 0;
  static constexpr int16_t VIEW_Y = 40;

  int16_t mapX(int16_t x) const { return VIEW_X + x * SCALE; }
  int16_t mapY(int16_t y) const { return VIEW_Y + y * SCALE; }

  Adafruit_ILI9341 tft_;
  uint8_t rotation_ = 1;
  uint8_t textSize_ = 1;
  uint8_t brightness_ = 255;
};

class ButtonShim {
 public:
  explicit ButtonShim(int pin) : pin_(pin) {}

  void begin() {
    pinMode(pin_, INPUT_PULLUP);
    current_ = digitalRead(pin_);
  }

  void update() {
    bool previous = current_;
    current_ = digitalRead(pin_);
    pressed_ = previous == HIGH && current_ == LOW;
  }

  bool wasPressed() {
    bool result = pressed_;
    pressed_ = false;
    return result;
  }

 private:
  int pin_;
  bool current_ = HIGH;
  bool pressed_ = false;
};

struct Config {};

class M5UnifiedShim {
 public:
  DisplayShim Display;
  ButtonShim BtnA{BUTTON_A_PIN};
  ButtonShim BtnB{BUTTON_B_PIN};

  Config config() { return Config{}; }

  void begin(const Config &) {
    Display.begin();
    BtnA.begin();
    BtnB.begin();
  }

  void update() {
    BtnA.update();
    BtnB.update();
  }
};

}  // namespace gar_wokwi_m5

static gar_wokwi_m5::M5UnifiedShim M5;
"""

    def _default_readme(self) -> str:
        return """# GAR Wokwi M5StackC Simulation

This project is generated by `gar sim env start` when the Wokwi simulation
backend is selected.

Build:

```bash
pio run
```

Run with Wokwi CLI:

```bash
export WOKWI_CLI_TOKEN=...
wokwi-cli .
```

Override paths with `GAR_WOKWI_PROJECT_DIR`, `GAR_WOKWI_FIRMWARE`,
`GAR_WOKWI_ELF`, and `GAR_WOKWI_TIMEOUT_MS`.
"""

    def _start_cli(self) -> int:
        cli = shutil.which("wokwi-cli")
        firmware = self._firmware_path()
        if not cli:
            self._print_payload(
                {
                    "provider": "wokwi",
                    "project_dir": str(self.project_dir),
                    "status": "project-ready",
                    "ok": True,
                    "warning": "wokwi-cli not found; install it to run the simulation",
                }
            )
            return 0
        if not self._relative_path_exists(firmware):
            self._print_payload(
                {
                    "provider": "wokwi",
                    "project_dir": str(self.project_dir),
                    "status": "project-ready",
                    "ok": True,
                    "warning": f"firmware not found: {firmware}; run `pio run` or set GAR_WOKWI_FIRMWARE",
                }
            )
            return 0

        timeout = self._timeout_ms()
        argv = [cli, str(self.project_dir), "--serial-log-file", str(self.log_path), "--timeout", str(timeout)]
        if timeout > 0:
            argv.extend(["--timeout-exit-code", "0"])
        log = self.log_path.open("ab")
        try:
            proc = subprocess.Popen(argv, cwd=self.project_dir, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        finally:
            log.close()
        self._write_state(
            {
                "provider": "wokwi",
                "pid": proc.pid,
                "argv": argv,
                "project_dir": str(self.project_dir),
                "log": str(self.log_path),
                "started_at": _now_iso(),
                "timeout_ms": timeout,
            }
        )
        self._print_payload({"provider": "wokwi", "status": "running", "pid": proc.pid, "project_dir": str(self.project_dir), "ok": True})
        return 0

    def start(self, hw_definition: dict[str, list[dict[str, str]]]) -> int:
        self._ensure_project(hw_definition)
        state = self._state()
        pid = state.get("pid")
        if isinstance(pid, int) and _is_pid_running(pid):
            self._print_payload({"provider": "wokwi", "status": "running", "pid": pid, "project_dir": str(self.project_dir), "ok": True})
            return 0
        return self._start_cli()

    def stop(self, hw_definition: dict[str, list[dict[str, str]]]) -> int:
        del hw_definition
        state = self._state()
        pid = state.get("pid")
        if not isinstance(pid, int) or not _is_pid_running(pid):
            self._write_state({**state, "stopped_at": _now_iso(), "status": "stopped"})
            self._print_payload({"provider": "wokwi", "status": "stopped", "ok": True})
            return 0
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        self._write_state({**state, "stopped_at": _now_iso(), "status": "stopped"})
        self._print_payload({"provider": "wokwi", "status": "stopped", "pid": pid, "ok": True})
        return 0

    def status(self, hw_definition: dict[str, list[dict[str, str]]], json_output: bool = False) -> int:
        del hw_definition
        state = self._state()
        pid = state.get("pid")
        running = isinstance(pid, int) and _is_pid_running(pid)
        payload = {
            "provider": "wokwi",
            "status": "running" if running else "stopped",
            "running": running,
            "pid": pid if isinstance(pid, int) else None,
            "project_dir": str(self.project_dir),
            "diagram": str(self.project_dir / "diagram.json"),
            "wokwi_toml": str(self.project_dir / "wokwi.toml"),
            "log": str(self.log_path),
            "cli": shutil.which("wokwi-cli"),
            "token": bool(os.environ.get("WOKWI_CLI_TOKEN")),
            "ok": True,
        }
        self._print_payload(payload, json_output=json_output)
        return 0

    def log(self) -> int:
        if not self.log_path.exists():
            print(f"wokwi log not found: {self.log_path}", file=sys.stderr)
            return 1
        print(self.log_path.read_text(encoding="utf-8", errors="replace"), end="")
        return 0

    def diag_json(self, hw_definition: dict[str, list[dict[str, str]]]) -> int:
        self._ensure_project(hw_definition)
        payload = {
            "provider": "wokwi",
            "ok": True,
            "project_dir": str(self.project_dir),
            "files": {
                "diagram": (self.project_dir / "diagram.json").exists(),
                "wokwi_toml": (self.project_dir / "wokwi.toml").exists(),
                "platformio": (self.project_dir / "platformio.ini").exists(),
                "firmware": self._relative_path_exists(self._firmware_path()),
                "elf": self._relative_path_exists(self._elf_path()),
            },
            "cli": shutil.which("wokwi-cli"),
            "token": bool(os.environ.get("WOKWI_CLI_TOKEN")),
            "m5stackc": {
                "board": "M5StickC/M5StackC-style ESP32",
                "display": "ILI9341-compatible TFT on SPI",
                "buttons": ["BtnA GPIO37", "BtnB GPIO39"],
            },
        }
        self._print_payload(payload, json_output=True)
        return 0

    def gpio_sim_check(self, json_output: bool = False) -> int:
        self._print_payload(
            {"provider": "wokwi", "gpio_sim": "not-applicable", "reason": "Wokwi models MCU pins directly", "ok": True},
            json_output=json_output,
        )
        return 0

    def gpio_command(self, command: str, hw_definition: dict[str, list[dict[str, str]]], json_output: bool = False) -> int:
        del hw_definition
        self._print_payload(
            {"provider": "wokwi", "command": command, "ok": True, "status": "unsupported", "reason": "Use Wokwi scenarios or serial input for MCU pin stimuli"},
            json_output=json_output,
        )
        return 0

    def panel(self, action: str, params: dict, json_output: bool = False) -> int:
        self._print_payload(
            {"provider": "wokwi", "action": action, "params": params, "ok": True, "status": "unsupported", "reason": "Wokwi UI/scenarios replace the Linux virtual hardware panel"},
            json_output=json_output,
        )
        return 0
