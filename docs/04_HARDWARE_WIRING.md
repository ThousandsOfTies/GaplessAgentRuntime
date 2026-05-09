# ハードウェア配線

実機（Raspberry Pi 5）でデモを動かすための配線。

---

## 必要なもの

| 物 | 用途 |
|---|---|
| ブレッドボード | 配線の土台 |
| ジャンパーワイヤー（オス-メス） | RasPi GPIO ↔ ブレッドボード |
| ジャンパーワイヤー（オス-オス） | ブレッドボード内 |
| LED | 点灯確認 |
| 抵抗 330Ω | LED の電流制限 |
| 抵抗 10kΩ | ボタンのプルダウン |
| タクトスイッチ | ボタン |

電子工作スターターキットを買うのが一番楽。

---

## LED + ボタン デモの配線

`gpio_led_button` を実機で動かすための配線。

```mermaid
flowchart LR
    subgraph RasPi5
        P1["Pin 1<br/>3.3V"]
        P6["Pin 6<br/>GND"]
        P11["Pin 11<br/>GPIO17"]
        P12["Pin 12<br/>GPIO18"]
    end

    subgraph LED回路
        R330["抵抗 330Ω"]
        LED_A["LED アノード (+)"]
        LED_K["LED カソード (−)"]
    end

    subgraph ボタン回路
        SW1["タクトスイッチ"]
        R10k["抵抗 10kΩ<br/>(プルダウン)"]
    end

    P12 --> R330
    R330 --> LED_A
    LED_A --> LED_K
    LED_K --> P6

    P11 --> SW1
    SW1 --> P1
    P11 --> R10k
    R10k --> P6
```

- **LED 回路**: GPIO18 → 抵抗 → LED → GND（電流制限のために抵抗が必要）
- **ボタン回路**: 押すと GPIO17 が 3.3V に繋がる。押していない時は 10kΩ 抵抗で GND に落として 0V を維持（プルダウン）

---

## VL53L0X（I2C 距離センサー）の配線

```mermaid
flowchart LR
    subgraph RasPi5
        P1["Pin 1<br/>3.3V"]
        P3["Pin 3<br/>GPIO2 / SDA"]
        P5["Pin 5<br/>GPIO3 / SCL"]
        P6["Pin 6<br/>GND"]
    end

    subgraph VL53L0X
        VCC
        GND
        SDA
        SCL
    end

    P1 --> VCC
    P6 --> GND
    P3 --> SDA
    P5 --> SCL
```

I2C はデフォルト無効。`sudo raspi-config nonint do_i2c 0 && sudo reboot` で有効化。

---

## MFRC-522（SPI RFID リーダー）の配線

```mermaid
flowchart LR
    subgraph RasPi5
        P1["Pin 1<br/>3.3V"]
        P6["Pin 6<br/>GND"]
        P15["Pin 15<br/>GPIO22 (任意)"]
        P19["Pin 19<br/>GPIO10 / MOSI"]
        P21["Pin 21<br/>GPIO9 / MISO"]
        P23["Pin 23<br/>GPIO11 / SCK"]
        P24["Pin 24<br/>GPIO8 / CE0"]
    end

    subgraph MFRC522
        M_VCC["3.3V"]
        M_GND["GND"]
        M_RST["RST"]
        M_MOSI["MOSI"]
        M_MISO["MISO"]
        M_SCK["SCK"]
        M_SDA["SDA (CS)"]
    end

    P1 --> M_VCC
    P6 --> M_GND
    P15 --> M_RST
    P19 --> M_MOSI
    P21 --> M_MISO
    P23 --> M_SCK
    P24 --> M_SDA
```

SPI も `sudo raspi-config nonint do_spi 0 && sudo reboot` で有効化。

---

## LCD HAT（240x240 ST7789）

「HAT」型のモジュールは RasPi5 の 40 ピン GPIO ヘッダに直接かぶせる。ブレッドボード不要。

---

## ピン配置の参考

- [pinout.xyz](https://pinout.xyz/) — インタラクティブなピン配置図
- [Raspberry Pi 公式ドキュメント](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#gpio)
