# Changelog

## 2026-06-24 — MANT reliability pass

- **Decision loop and recognition speed.** Executor sleep reduced from 80 ms to 60 ms. Race scanning now forces recognition on the first four passes instead of relying on a single attempt, catching mandatory races that were being missed on the first scan. CNN digit recognition is batched across all stats per facility into a single GPU call (previously one call per stat, ~10 per facility).

- **MANT debut retry.** The debut race now arms a scenario-specific retry guard, checks the actual race result screen before pressing Next, and can spend up to 5 clocks on debut only. It reads both the Try Again button state and the large top-left race rank (`1st`, `16th`, etc.) and does not rely on the lower result list.

- **Safer race-result flow.** MANT debut retry now runs inside the `RACE_RESULT` handler itself, preventing the bot from skipping past Try Again before the retry logic sees it.

- **Shop and inventory syncing.** Inventory is forcefully rescanned every 6 turns to overwrite stale memory — fixing ghost items that were stuck at zero despite being in the bag. Shop scans sample more aggressively during scroll, and the buy flow is more willing to spend coins on configured valid items.

- **Shop priorities and exclusions.** MANT item tiers now support a visible `Disabled / Never Buy` bucket, strict enabled-tier priority, and hard exclusion for disabled items even when contextual overrides would normally want them.

- **Recovery item behavior.** Training recovery was tightened so the bot checks usable recovery resources before resting and rescans training in place after item use — no unnecessary menu exit and re-enter to refresh failure rates. Royal Kale Juice now brings a cupcake (Berry Cupcake as fallback) into the same confirm panel, consuming both in a single action.

- **Megaphone and anklet handling.** Megaphone + anklet use can be batched into one inventory operation when safe, repeated same-turn anklet attempts are blocked, and megaphone duration now ticks once per real turn instead of once per training rescan.

- **User-controlled cleats and glow sticks.** Cleat and glow stick usage is now fully configured in the WebUI: master vs artisan priority, separate climax toggles, and exact race IDs for calendar races. The previous automatic logic is removed entirely. Glow sticks on climax are restricted to the last climax race only (turn 78).

- **Stat cap discipline.** When a stat reaches its target cap: the shop no longer buys items for that stat; the entire facility score is scaled down by a multiplier (not just the capped stat's contribution), making the bot more aggressively deprioritize over-capped facilities; OCR reads above 9,999 are treated as garbage and replaced with the previous turn's value.

- **Scroll behavior.** ADB vertical swipes use real-duration input, and shop/inventory/borrow-card scrolling is smoother and less prone to bouncing or ending early.

- **Safety stops.** The bot hard-stops with auto-restart disabled on the `Account Activity Warning` popup, matching the existing Veteran Max Umamusume guard behavior.

- **WebUI updates.** The run timer shows elapsed time while a task is active. The Cleats & Glow configuration section now sits below Race Options with On/Off buttons for all toggles.

- **Setup polish.** `config.yaml` is auto-created from the template on first run so the bot works out of the box without manual file copying. Windows startup scripts consistently use the venv.
