# HTML Report

The HTML report shows:
- Summary stats and per-module mutation scores
- Each mutant as a collapsible card with unified diff
- Color-coded status: killed (green), survived (red), error (orange)
- Full type checker output per mutant
- Expand/Collapse All controls

```bash
typemut html --open                     # save and open in browser
typemut html -o report.html             # save to specific file
```
