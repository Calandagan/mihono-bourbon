# Mihono-Bourbon

### 👉 [Join the official Discord](https://discord.gg/QJcnuXDKxv) — community, support and updates.

An Uma Musume bot that handles training, races, events, skill purchasing and full-run automation.

This is an independent build based on the original **Sweepy** (the /vg/ UAT rehash a lot of people already run). It started from that codebase, and the decision-making, race handling, shop, item usage and input were reworked to be faster, more aggressive where it matters, and more reliable. If you've used Sweepy this will feel familiar, it just behaves noticeably better, especially in MANT.

The whole point of this build is farming high-quality parents/grandparents. Expect roughly a **15–16k average** depending on your card setup. It can be used for fan farming too, but that isn't the focus.

Scenarios supported: **URA Finals**, **Unity Cup (Aoharu)**, **MANT** (functional, actively worked on).

> Heads up: if this ever runs into the kind of situation Sweepy did (you know the one), public updates will stop and development continues privately.

---

## What's different in this build

- **Faster, less wishy-washy decisions.** The turn loop runs tighter, the training scorer was cleaned up, and digit recognition is batched across stats per facility so the bot spends less time on perception and more time acting.
- **Required races actually get run.** Forced, scheduled, climax and user-configured races are handled more reliably. Race scanning retries with force on the first few passes so it doesn't miss mandatory races in the first sweep.
- **Aggressive, single-pass shop.** It buys everything you allow in one visit instead of leaving items for a later trip. The scan covers more of the list and the buy step no longer skips items it already detected. Items that genuinely can't be bought are dropped instead of being chased around the list.
- **Full control over cleats and glow sticks.** Configure which calendar races get a cleat, whether to use one on climax, and whether to use glow sticks at all — all from the WebUI. Glow sticks on climax are restricted to the final climax race. No more automatic guessing.
- **Per-stat caps that make sense.** Set a target on a stat and the bot stops chasing it once it's reached — both in training scoring and at the shop. It will still take an off-type training (e.g. a Speed slot stacked with Power) when that's the better click. See [Stat Caps](#stat-caps-target-attributes).
- **Smarter item usage.** Grilled Carrots are used the moment they're bought instead of piling up in your bag. Royal Kale Juice brings a cupcake into the same confirm panel. After using any recovery item the bot rescans training in place instead of exiting and re-entering the menu.
- **Inventory that stays accurate.** A full rescan overwrites memory every 6 turns, fixing ghost items that were stuck at zero despite being in the bag.
- **Precise input.** Taps and scrolls were tuned for accuracy and consistency instead of fake human jitter, so it lands on the right thing more often.

MANT is where most of this work went. It's still being refined, but it's solid for parent farming.

---

## Table of Contents

- [Requirements](#requirements)
- [Installation](#installation)
- [GPU Acceleration](#gpu-acceleration)
- [Emulator Setup](#emulator-setup)
- [Configuration](#configuration)
- [Stat Caps (Target Attributes)](#stat-caps-target-attributes)
- [Recommended Setup](#recommended-setup)
- [Troubleshooting](#troubleshooting)
- [Changelog](#changelog)
- [Disclaimer](#disclaimer)
- [Credits](#credits)

---

## Requirements

- Python 3.10
- Visual C++ Redistributable ([Download](https://aka.ms/vs/17/release/vc_redist.x64.exe))
- An Android emulator. MuMu Player is recommended. LDPlayer works as a fallback if you can't run MuMu, but it isn't recommended. Avoid BlueStacks, it breaks screenshots in ways that aren't worth debugging.

---

## Installation

### Step 1: Clone the repository

```bash
git clone https://github.com/Calandagan/mihono-bourbon
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

On first run, `config.yaml` is created automatically from the template. Open it and set your emulator's ADB address before doing anything else.

---

## GPU Acceleration

Optional but recommended if you have an NVIDIA card. PaddleOCR is noticeably faster on GPU.

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

Set graphics to `Standard` in-game (not `Basic`), then manually select your Uma Musume, Legacy Uma and Support Cards before starting. The bot won't change those for you.

Most settings live in the **WebUI**, which opens automatically when you start the bot. The main things to configure before your first run:

**In the WebUI task editor:**
- **Race selection** — add the calendar races you want to run. These are also the races you can assign cleats and glow sticks to individually.
- **Target Attributes** — stat caps. Leave at 9999 to never cap a stat. See [Stat Caps](#stat-caps-target-attributes).
- **Training weights** — push the bot toward specific stats by raising their weight. Stats with higher weight score better, so the bot will favour those facilities.
- **Block Training At Or Above Failure Rate** — 15% or lower is recommended. Higher values mean the bot trains through riskier situations.
- **Item tiers** — controls what the shop buys and in what priority order. Tier 0 means never buy.
- **Cleats & Glow Sticks** — set priority (master vs artisan), toggle climax use, and pick specific race IDs for calendar races.

**In `config.yaml`:**
- Set your emulator's ADB address (`device_name`).
- Toggle GPU acceleration (`gpu.enabled`).
- Adjust `cpu_alloc` if PaddleOCR is competing with other processes.

**In `main.py`:**
- Daily runtime limit (default 20 hours).

---

## Stat Caps (Target Attributes)

Stat caps tell the bot when to stop prioritizing a stat. Set them in the **Target Attributes** field, one value per stat in this order: **Speed, Stamina, Power, Guts, Wit**.

### Default
Every stat defaults to **9999** — no cap, the bot always trains whatever scores best.

### Capping a stat
Set the stat's target to the value you want, e.g. Speed `1040`. Once Speed reaches 1040:

- Speed gains stop counting toward the score, so the bot moves on to your next priority stat.
- The facility's overall score is scaled down, not just the Speed contribution — so the bot more aggressively avoids over-capped facilities rather than still clicking them for scraps.
- It still considers a Speed facility if it gives enough of the **other** stats. A card-buffed Speed slot that hands you more Power than the Power slot is still worth clicking, and the bot will take it.
- The shop stops buying stat-specific items for capped stats.

Leave a stat at 9999 to never cap it. The cap kicks in the moment the stat reaches the value, no turn requirement.

---

## Recommended Setup

- Run at least **34 races** plus the **3 mandatory climax races**.
- Bring cards with a high race bonus (Nishino Flower, Marvelous Sunday, Nice Nature, etc.).
- Use umas with 2–3 aptitudes so you can run more races. Aptitudes should be **B minimum, A for optimal**.
- Set the skill point learning threshold to **3000** to stop the bot from spending time buying skills mid-run. Buy skills manually at the end instead.
- There's **no general race-retry logic**, on purpose. The only exception is MANT debut: the bot can spend a capped number of clocks there because losing debut can ruin the whole run.

---

## Troubleshooting

### Bot stuck in a menu
Disable "Keep alive in background" in the emulator settings.

### ADB connection fails
Restart your machine. If it keeps happening, check that the ADB address in `config.yaml` matches what the emulator reports.

### Stats not showing in scoring
Install or reinstall the Visual C++ Redistributable:
[Download vc_redist.x64.exe](https://aka.ms/vs/17/release/vc_redist.x64.exe)

### PaddleOCR crashes or runs very slow
GPU setup isn't complete. Follow the [GPU Acceleration](#gpu-acceleration) steps. If you don't have an NVIDIA card, set `gpu.enabled: false` in `config.yaml`.

### Bot owns items but doesn't use them
Inventory memory can get stale. The bot automatically overwrites it every 6 turns. If items still aren't being used after that, check that the item tier in the WebUI isn't set to 0 (disabled).

### Impossible stat numbers in the logs (e.g. 324333246)
This is an OCR artifact, not a real read. The bot catches these, discards them, and falls back to the previous turn's value automatically. No action needed.

---

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for the full history.

**Latest (2026-06-24):** Decision loop speed, MANT debut retry, user-controlled cleats/glow sticks, stat cap discipline improvements, in-place recovery rescan, periodic inventory overwrite, and WebUI updates.

---

## Disclaimer

**Use at your own risk.** I'm not responsible for anything that happens to your account, and I honestly don't care if you get banned. We're adults, make your own decisions and live with the consequences.

There's no security risk here. I'm not a loser, there are no backdoors, keyloggers, or anything shady in this project.

Machines with an **NVIDIA GPU** will perform better. No idea how it runs without one.

P.S. Cygames, you can suck my BBC. You want us to stop botting? Add the damn autoplay and quality-of-life changes :)

---

## Credits

This build wouldn't exist without the work it's based on:

- **Sweepy** — the /vg/ UAT rehash this build started from.
- **Original repository**: [UmamusumeAutoTrainer](https://github.com/shiokaze/UmamusumeAutoTrainer) by [Shiokaze](https://github.com/shiokaze)
- **Global server port**: [UmamusumeAutoTrainer-Global](https://github.com/BrayAlter/UAT-Global-Server) by [BrayAlter](https://github.com/BrayAlter)
