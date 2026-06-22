# Mihono-Bourbon

An Uma Musume bot that handles training, races, events, skill purchasing and full-run automation.

This is an independent build based on the original **Sweepy** (the /vg/ UAT rehash a lot of people already run). It started from that codebase, and the decision-making, race handling, shop, item usage and input were reworked to be faster, more aggressive where it matters, and more reliable. If you've used Sweepy this will feel familiar, it just behaves noticeably better, especially in MANT.

![Uma Musume Auto Trainer](docs/main.png)

> Heads up: if this ever runs into the kind of situation Sweepy did (you know the one), public updates will stop and development continues privately.

---

## What's different in this build

- **Faster, less wishy-washy decisions.** The training scorer was cleaned up and the turn loop wastes less time second-guessing itself.
- **Required races actually get run.** Forced, scheduled, climax and user-configured races are handled more reliably.
- **Aggressive, single-pass shop.** It buys everything you allow in one visit instead of leaving items for a later trip. The scan covers more of the list and the buy step no longer skips items it already detected. Items that genuinely can't be bought are dropped instead of being chased around the list.
- **Aggressive cleat usage, on purpose.** Cleats get used freely across regular races (G1/G2/G3), while the bot tries to keep some in reserve for climax. This is intentional for now and still being tuned.
- **Per-stat caps that make sense.** Set a target on a stat and the bot stops chasing it once it's reached, but it will still take an off-type training (e.g. a Speed slot stacked with Power) when that's the better click. See [Stat Caps](#stat-caps-target-attributes).
- **Smarter item usage.** Grilled Carrots are used the moment they're bought instead of piling up in your bag, and megaphone/anklet behavior is easier to reason about.
- **Precise input.** Taps and scrolls were tuned for accuracy and consistency instead of fake human jitter, so it lands on the right thing more often.

MANT is where most of this work went. It's still being refined, but it's solid for parent farming.

---

## Table of Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Emulator Setup](#emulator-setup)
- [Configuration](#configuration)
- [Stat Caps (Target Attributes)](#stat-caps-target-attributes)
- [GPU Acceleration](#gpu-acceleration)
- [Troubleshooting](#troubleshooting)
- [Credits](#credits)

---

## Features

### Fully automated training
- Hands-off operation for days of continuous training
- Automatic TP recovery and run initialization
- Recovers from disconnections, crashes and game updates
- Background play through mobile emulators

### Scenario support
- URA Finals
- Unity Cup (Aoharu)
- MANT (functional, actively worked on)

### Deep customization
- Almost everything that can be detected is detected and used: skill hint levels, energy changes, stat gains, and more
- A lot of settings to tune the bot to your deck and goals
- Gimmick cards (energy cost reduction, training effectiveness, etc.) can be used to their full extent

---

## Requirements

- Python 3.10
- Visual C++ Redistributable ([Download](https://aka.ms/vs/17/release/vc_redist.x64.exe))
- An Android emulator. MuMu Player is recommended. LDPlayer works as a fallback if you can't run MuMu, but it isn't recommended. Avoid BlueStacks, it breaks screenshots in ways that aren't worth debugging.

---

## Installation

### Step 1: Clone the repository

```bash
git clone https://github.com/ghostgunnat/mihono-bourbon
cd mihono-bourbon
```

### Step 2: Install Python 3.10 and VC++

```bash
winget install -e --id Python.Python.3.10
```
Visual C++ Redistributable: https://aka.ms/vs/17/release/vc_redist.x64.exe

### Step 3: Install dependencies

```bash
pip install -r requirements.txt
```

### Step 4: Run the bot

```bash
python main.py
```

Or just run `start.bat`.

---

## Emulator Setup

### Display
- **Resolution**: 720 x 1280 (portrait)
- **DPI**: 180
- **FPS**: 30 or higher (don't go below 30)

### Graphics
- **Rendering**: Standard (not Simple/Basic)
- **ADB**: must be enabled in the emulator settings

### Emulators
- MuMu Player (recommended)
- LDPlayer (fallback only, if you can't run MuMu — not recommended)

---

## Configuration

1. Set graphics to `Standard` in-game (not `Basic`).
2. Manually select your Uma Musume, Legacy Uma and Support Cards before starting.
3. Edit your runtime in `main.py` (default is 20 hours a day).
4. **Failure rate**: keeping "Block Training At Or Above Failure Rate" at 15% or lower is recommended, but it's your call.
5. **Stat weights**: use the per-stat training weights (the `Weight` values in the score formula: `Speed × Weight`, `Power × Weight`, etc.) to push the bot toward the stats you actually want to prioritize.

---

## Stat Caps (Target Attributes)

Stat caps tell the bot when to stop prioritizing a stat. You set them in the **Target Attributes** field, one value per stat in this order: **Speed, Stamina, Power, Guts, Wit**.

### Default
Every stat defaults to a high value (**9999**), which means "no cap": the bot always trains whatever scores best.

### Capping a stat
Set the stat's target to the value you want, e.g. Speed `1040`. Once Speed reaches 1040:

- Speed gains stop counting toward the score, so the bot moves on to your next priority stat.
- It still considers a Speed facility if it gives enough of the **other** stats. A card-buffed Speed slot that hands you more Power than the Power slot is still worth clicking, and the bot will take it.

It's a clean per-stat cutoff (no soft gradient). Leave a stat at 9999 to never cap it. There's no turn requirement, the cap kicks in the moment the stat reaches the value.

![Default Stat Caps](docs/statCaps.png)
![Speed Cap Example](docs/capSpeed.png)

---

## GPU Acceleration

Optional NVIDIA GPU acceleration for better performance.

### Prerequisites
1. NVIDIA GPU with current drivers
2. CUDA Toolkit 11.8 ([Download](https://developer.nvidia.com/cuda-11-8-0-download-archive))
3. cuDNN v8.6.0 for CUDA 11.x ([Download](https://developer.nvidia.com/rdp/cudnn-archive))

### Steps

1. Extract cuDNN and copy its contents into the CUDA folders:
   ```
   cudnn-windows-x86_64-8.6.0.163_cuda11-archive\bin
   -> C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v11.8\bin
   ```
   Repeat for the other cuDNN folders (bin, include, lib).

2. Add to system PATH:
   - `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v11.8\bin`
   - `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v11.8\libnvvp`
   - `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v11.8`

3. Copy and rename zlib:
   ```
   C:\Program Files\NVIDIA Corporation\Nsight Systems 2022.4.2\host-windows-x64\zlib.dll
   -> C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v11.8\bin\zlibwapi.dll
   ```

4. Install the GPU build of PaddlePaddle:
   ```bash
   pip uninstall paddlepaddle
   pip install paddlepaddle-gpu==2.6.2 -i https://pypi.tuna.tsinghua.edu.cn/simple
   ```

5. Update `requirements.txt`:
   ```
   paddlepaddle-gpu==2.6.2
   ```

6. Reboot.

---

## Troubleshooting

### Bot stuck in a menu
Disable "Keep alive in background" in the emulator settings.

### ADB connection fails
Restart your machine.

### Stats not showing in scoring
Install or reinstall the Visual C++ Redistributable:
- [Download vc_redist.x64.exe](https://aka.ms/vs/17/release/vc_redist.x64.exe)

![Stats Display](https://github.com/user-attachments/assets/1f68af35-cf9d-41ce-9392-c26ecf83cc70)

---

## Credits

This build wouldn't exist without the work it's based on:

- **Sweepy** — the /vg/ UAT rehash this build started from.
- **Original repository**: [UmamusumeAutoTrainer](https://github.com/shiokaze/UmamusumeAutoTrainer) by [Shiokaze](https://github.com/shiokaze)
- **Global server port**: [UmamusumeAutoTrainer-Global](https://github.com/BrayAlter/UAT-Global-Server) by [BrayAlter](https://github.com/BrayAlter)

---

![Uma Musume](docs/umabike.gif)
![Uma Musume](docs/flower.gif)
