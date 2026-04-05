# Shop Purchase Fix - Summary

## Problem
The bot was scanning the MANT shop, identifying purchase targets correctly (shown in logs), but failing to actually buy items. It would scroll through the shop list endlessly without clicking anything.

## Root Cause
The `buy_shop_items()` function in `shop.py` was **re-detecting items from scratch using OCR** instead of using the already-scanned data from `scan_mant_shop()`. This caused several issues:

1. **OCR Unreliability**: The synchronous scroll-and-detect loop often failed to recognize items
2. **Different Detection Methods**: 
   - `scan_mant_shop` uses sophisticated async scrolling with frame deduplication
   - `buy_shop_items` used simple synchronous OCR - much less reliable
3. **Items Not Detected**: Items in the target list weren't being found by the OCR, so `name_candidates` stayed empty
4. **Infinite Scrolling**: The 60-iteration loop kept scrolling but finding nothing to click

## Solution
Modified `buy_shop_items()` to **use the pre-scanned shop data** when available:

### Changes Made:

1. **`shop.py` - `buy_shop_items()` function**:
   - Added check: if `items_list` is provided, use `_buy_from_scanned_data()` helper
   - Falls back to old OCR-based method only if no scanned data available
   - New helper function `_buy_from_scanned_data()` uses global Y coordinates from scan to navigate

2. **`main_menu.py` - `handle_mant_shop_scan()` function**:
   - Added DEBUG log to verify scanned items are being passed to purchase function
   - This helps diagnose if the issue is in scanning vs purchasing

### How It Works Now:

```
1. scan_mant_shop() runs and returns:
   - items_list: [(name, conf, gy, turns, bought), ...]
   - ratio: scroll ratio
   - first_item_gy: global Y of first item

2. Targets are calculated from items_list

3. buy_shop_items() is called WITH the scanned data

4. NEW: Instead of re-OCRing, it:
   - Scrolls to top (known position)
   - For each wanted item:
     * Calculates estimated screen Y from global Y
     * Verifies item is buyable at that position
     * Clicks the checkbox
     * Scrolls to next item
   - Confirms purchases
```

## Testing
After applying this fix, you should see in the logs:
- `Using pre-scanned shop data for purchasing (X items)`
- `Attempting to purchase X items using scanned positions`
- `purchasing <ItemName> at y=<position>`
- `Confirming purchase of X items: {...}`

## Benefits
1. **More Reliable**: Uses accurate scanned data instead of unreliable OCR re-detection
2. **Faster**: No need to re-scan the entire shop
3. **Consistent**: Same detection method for both scanning and purchasing
4. **Backwards Compatible**: Falls back to old method if no scanned data available

## Files Modified
- `C:\Games\umamusume-sweepy\module\umamusume\scenario\mant\shop.py`
- `C:\Games\umamusume-sweepy\module\umamusume\scenario\mant\main_menu.py`
