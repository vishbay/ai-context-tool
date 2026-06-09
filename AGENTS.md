<!-- cram-ai: start -->
# Current Task

## Task
<!-- Session ended on commit. Run `cram task "..."` or use the tray to begin a new task. -->

## Relevant Files
<!-- Populated by `cram task "..."` -->

## Command Output Protection

Every command with unknown or potentially large output MUST be byte-capped.

Default rule: COMMAND 2>&1 | head -c 6000

Safe patterns:
  head -n 50 file.py | cat
  git status --porcelain | head -n 30
  git log --oneline -15
  grep -n "KEYWORD" file.py | head -n 40

Write-then-inspect for large outputs:
  COMMAND > .cram-temp-output.txt 2>&1
  head -c 6000 .cram-temp-output.txt

Never cat a file over 200 lines without head/tail.
Never run a script with unknown output without | head -c 6000.
<!-- cram-ai: end -->
