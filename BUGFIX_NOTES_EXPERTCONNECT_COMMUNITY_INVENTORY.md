# MkulimaBridge UI Bug Fixes

## Issues addressed

### 1. Community Pulse report submission
The report API could save a report successfully, but the frontend then called `event.currentTarget.reset()` after awaiting the network request. Browsers set `event.currentTarget` to `null` after event dispatch completes, so the form reset threw a TypeError and the UI incorrectly displayed a failed submission message.

**Fix:** Capture the form element before the first `await` and call `form.reset()` after the API confirms the save. The farmer now sees the saved-report confirmation and the community totals refresh.

### 2. Inventory item submission
The inventory API could save the item successfully, but the same asynchronous `event.currentTarget.reset()` issue then made the UI report a false failure.

**Fix:** Capture a stable form reference before awaiting the API, reset the saved form safely, and refresh inventory and workspace summaries.

### 3. ExpertConnect case chooser
The case chooser originally loaded only during initial page startup. If a farmer created a crop or livestock case afterwards, the chooser could remain empty until the page was reloaded.

**Fixes:**
- Load up to 100 cases belonging to the signed-in farmer.
- Include both crop and livestock cases in the same chooser.
- Refresh automatically when a new crop or livestock case is saved.
- Refresh when the farmer opens ExpertConnect.
- Add a manual **Refresh case list** button.
- Display a helpful message when this account has no saved cases yet or when the case list cannot be loaded.
- Show the case type and crop/species in each option.

### 4. Other asynchronous form resets
The same unsafe pattern was also present in the reminder form, case-action form and password-change form.

**Fix:** Those handlers now capture the form element before awaiting requests and reset the captured element after success.

## Validation

- Backend automated tests: 56 passed, 1 skipped in this packaging environment.
- Frontend JavaScript syntax: all files passed `node --check`.
- HTML structure parse: passed; 244 unique IDs and no duplicate IDs.
- Added regression tests for mixed crop/livestock ExpertConnect case listing, async form reset handling, and automatic/manual ExpertConnect list refresh.

## Notes

- Community Pulse still suppresses shared trend groups below the minimum aggregation threshold for privacy. Individual report submission confirmation and overall report count should update immediately.
- ExpertConnect prepares a farmer-controlled summary. It does not automatically contact or assign a verified expert.
- The application remains a local MVP and requires production-grade account security, PostgreSQL deployment and operational review before public use.
