# Race Search Loop Fix - Summary

## Problem
The bot got stuck searching for race 2265 (Tenno Sho Spring) in an infinite loop. It would:
1. Scroll through the race list
2. Detect "Bottom reached"
3. Spam scroll for 3.7 seconds
4. Start searching again
5. Never find the race
6. Repeat forever

The logs show this pattern repeating multiple times:
```
07:14:14 - Bottom reached
07:14:25 - Bottom reached
(and would continue indefinitely)
```

## Root Cause
The race search loop in `race_handlers.py` (lines 181-211) had a critical flaw:

1. **No "bottom reached" tracking**: The code didn't count how many times it hit the bottom
2. **Infinite loop**: After spam scrolling, it continued searching without any progress tracking
3. **Race not available**: The race 2265 was likely not in the list (not unlocked yet, wrong date, etc.)
4. **No recovery**: Even though there was a 30-second timeout, the bot kept looping wastefully

The loop structure was:
```python
while True:
    if timeout > 30s: return
    selected = find_race(img, race_id)
    if selected: return
    if bottom_reached:
        spam_scroll(3.7s)
    scroll_up()  # Keep searching forever
```

## Solution
Added **bottom detection counting** with early exit logic:

### Changes Made:

**`race_handlers.py` - `script_cultivate_race_list()` function**:

1. **Track bottom count**: Added `ti.race_search_bottom_count` to track how many times we hit bottom
2. **Early exit**: If bottom is reached 3+ times, assume race is not available and return to main menu
3. **Better logging**: Log the bottom count to help diagnose issues
4. **Clean state management**: Properly clean up all tracking attributes on exit
5. **Reset on scroll up**: Reset bottom count if we successfully scroll up (race might be further up)

### New Logic Flow:

```python
while True:
    if timeout > 30s:
        cleanup()
        return_to_menu()
        return
    
    selected = find_race(img, race_id)
    if selected:
        cleanup()
        click_race()
        return
    
    if bottom_reached:
        bottom_count += 1
        if bottom_count >= 3:
            # Race probably not available
            cleanup()
            return_to_menu()
            return
        spam_scroll(3.7s)
        continue
    
    scroll_up()
```

## Benefits

1. **Faster recovery**: Exits after ~10-15 seconds (3 bottom hits) instead of 30+ seconds
2. **Prevents infinite loops**: Won't search forever for unavailable races
3. **Better diagnostics**: Logs show exactly how many times bottom was reached
4. **Graceful degradation**: Returns to main menu to continue training instead of getting stuck
5. **Smart detection**: Resets counter if scrolling up successfully (race might be in view)

## Expected Behavior After Fix

When a race is not found:
```
Looking for race ID: 2265
Bottom reached (count: 1)
Looking for race ID: 2265
Bottom reached (count: 2)
Looking for race ID: 2265
Bottom reached (count: 3)
Race 2265 not found after hitting bottom 3 times - race may not be available
```

Then the bot will:
1. Clear the race operation
2. Return to main menu
3. Continue with normal training logic
4. Possibly try again on a future turn when the race becomes available

## Files Modified
- `C:\Games\umamusume-sweepy\module\umamusume\script\cultivate_task\race_handlers.py`

## Why Race 2265 Might Not Have Been Available

Possible reasons:
1. **Not unlocked yet**: Race requires certain conditions (fans, stat requirements, etc.)
2. **Wrong timing**: Race might not be registered for the current turn
3. **Scenario-specific**: MANT scenario might have different race availability
4. **List not refreshed**: Game might need a turn refresh to show new races

The fix handles all these cases gracefully by giving up and trying again later.
