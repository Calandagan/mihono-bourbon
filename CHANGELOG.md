# Changelog

## 2026-07-01 — Aoharu + MANT post-update compatibility pass

- **MANT shop open detection after game update.** Shop opening no longer depends only on the old `REF_SHOP_MANT_CHECK` template. It now confirms the MANT shop through the original check, a shop-title fallback, or a scrollbar/list fallback, with clearer diagnostics when none of them match.

- **MANT shop purchase accounting.** Shop purchases are tracked from actual buy-click results instead of optimistic target intent, reducing stale inventory assumptions when an item cannot actually be bought. Final-phase consumables are also burned more deliberately so the bot does not carry useful items past the point where they matter.

- **Aoharu WebUI modal fix.** The Aoharu Cup configuration modal no longer gets trapped behind the task-edit overlay. The manual backdrop is now scoped so it does not intercept clicks meant for the Aoharu config window.

- **Aoharu Team Zenith final showdown support.** The final `Team Showdown` screen was reconfigured around the updated Team Zenith layout. The bot now clicks the large `Race!` button on the final showdown screen and handles the new intermediate `Confirmation` popup by pressing `Begin Showdown!` instead of falling into the generic confirmation path.

- **Aoharu Team Zenith loop guard.** Pressing `Race!` now arms a short-lived Team Showdown confirmation state. If the next screen is classified as a generic `Confirmation`, the bot treats it as the Team Zenith popup and clicks `Begin Showdown!`, preventing the previous loop of opening and immediately closing the popup.

- **Training rest policy cleanup for URA/Aoharu.** The old low-energy fast path inside `training_select.py` that immediately forced rest has been removed. `rest_threshold` now acts as a trigger to review trainings, while `max_failure_rate` is the hard safety rule that decides whether training is allowed.

- **Failure-rate-first low-energy behavior.** URA and Aoharu now mirror the safer MANT flow: when energy is low, the bot enters training select, scans the available trainings, reads failure rates, blocks unsafe or unreadable trainings, and only rests or outings if no valid training remains.

- **URA/Aoharu speed mode for capped stats.** Added a WebUI toggle, `Skip capped training scans aggressively`, visible for URA and Aoharu. When enabled, facilities whose main stat has already reached the configured target attribute cap are skipped entirely during scan to reduce run time.

- **Training timing instrumentation.** Added more granular training timing logs: transition into training select, facility scan duration, scoring/decision time, and total training select evaluation time. This makes it easier to see whether time is being spent in UI transitions, OCR/scanning, or decision logic.

- **Aoharu final showdown tests.** Added tests covering the updated Team Zenith final screen and the new `Begin Showdown!` confirmation flow.

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
