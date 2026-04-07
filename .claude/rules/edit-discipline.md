# Edit Tool Discipline

When using the Edit tool (old_string -> new_string replacement):
- **Minimize the replacement scope.** Only include the lines you're actually changing. Do NOT select a 20-line block just to change 2 lines -- you WILL accidentally drop surrounding logic.
- **If you must replace a large block**, read it line by line and verify every line from `old_string` appears in `new_string` (unless intentionally removing it).
- **Prefer multiple small edits** over one big edit. Safer and easier to review.
- **Rename = Edit + Grep.** After renaming a variable/function via Edit, always `grep` the old name across the file (and related files) to confirm zero residual references. Edit only replaces within `old_string` scope — references outside that range will silently break.
