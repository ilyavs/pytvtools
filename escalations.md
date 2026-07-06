# Escalations

## Chrome session not computing indicators (RESOLVED)

Restarting the container fixed it. Indicators compute normally after restart.

## Python PVP parity with Pine PVP (RESOLVED)

Time-intersection matching using period markers from `get_indicator_data`. Each completed period's POC is computed on exact time-intersected LTF bars. Periods with partial LTF coverage are skipped.

### Final parity (BATS:GME, 60m, ±0.01 tolerance)

| Period | Overlapping periods | Matched | Rate |
|--------|-------------------|---------|------|
| Day    | 55                | 55      | 100% |
| Week   | 25                | 25      | 100% |
| Month  | 5                 | 5       | 100% |

### Why 100% is possible
- Time-intersection: each period is compared by exact time boundaries from Pine's `ta.change(time(unit))` markers
- Partial-period skip: periods where Python's 10m data starts mid-month are excluded (`p_start < ltf_first`)
- Proximity matching fallback (no markers) uses n_overlap filter: Day=96.4%, Week=88.5%, Month=71.4%

### Data limitation
- Python has 10,205 10m bars (~179 days) vs Pine's ~40K via `request.security_lower_tf("10")` (~990 days)
- Only the last 55/25/5 periods overlap; all earlier Pine POC lines correspond to periods outside Python's data range
